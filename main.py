import logging
import urllib2
import webapp2
import settings
import numpy
from pywt import dwt2

from PIL import Image
from google.appengine.api import images, taskqueue
from google.cloud.storage import Client
from google.appengine.ext import db
# from google.appengine.api import users

# from cors.cors_application import CorsApplication
# from cors.cors_options import CorsOptions

from requests_toolbelt.adapters import appengine
appengine.monkeypatch()


def get_storage_client():
    return Client(project=settings.PROJECT_NAME)


def resize_image(image, new_image):
    image.resize(width=int(new_image.image_width), height=int(new_image.image_height))
    return image


def get_image_by_url(url):
    image_at_url = urllib2.urlopen(url)
    image_bytes = image_at_url.read()
    image_at_url.close()
    image = images.Image(image_bytes)
    return image


def get_thumbnail_image(new_image, url):
    logging.info("get thumbnail image by url: {}".format(url))
    image = get_image_by_url(url)
    if new_image.image_height and new_image.image_width:
        image = resize_image(image, new_image)
    jpeg = images.images_service_pb.OutputSettings.JPEG
    thumbnail = image.execute_transforms(output_encoding=jpeg, quality=new_image.quality)
    return thumbnail


def get_image_size(new_image):
    image_at_url = urllib2.urlopen(str(new_image.image_url))
    im = PIL.Image.open(image_at_url)
    image_at_url.close()
    new_image.image_width, new_image.image_height = im.size
    return new_image


def get_blob(new_image):
    client = get_storage_client()
    bucket = client.bucket(new_image.bucket_name)
    blob = bucket.blob(new_image.image_name)
    return blob


def update_image_in_bd(db_image, new_image):
    db_image.original_url = new_image.image_url
    blob = get_blob(new_image)
    db_image.processed_url = blob.public_url
    db_image.save()


class CrunchoImage(db.Model):
    name = db.StringProperty()
    original_url = db.StringProperty()
    processed_url = db.StringProperty()
    blurred = db.StringProperty()
    created = db.DateTimeProperty(auto_now_add=True)


class Filter(object):
    def __init__(self, view, fields):
        self.view = view
        for name, key in fields.items():
            if key == 'image_width' or key == 'image_height':
                setattr(self, name, view.get(key))
            else:
                setattr(self, name, view.get(key, None))
        setattr(self, 'bucket_name', settings.BUCKET_NAME)

    @property
    def create_task_save_image(self):
        taskqueue.add(
            url='/save_image',
            params={'image_url': self.image_url,
                    'image_name': self.image_name,
                    'image_width': self.image_width,
                    'image_height': self.image_height,
                    'bucket_name': self.bucket_name}
        )


class MainPage(webapp2.RequestHandler):

    def get(self):
        self.response.headers.add_header('Access-Control-Allow-Origin', settings.ACCESS_CONTROL_ALLOW_ORIGIN)
        self.response.headers['Content-Type'] = 'text/plain'

        fields = {
            'quality': 'quality',
            'image_width': 'image_width',
            'image_height': 'image_height',
            'image_name': 'image_name',
            'image_url': 'image_url',
            'blurred': 'blurred'
        }

        new_image = Filter(self.request, fields)

        if self.request.headers.get('Host') not in settings.ACCESS_LIST:
            return self.response.write('\n\nYou do not have access rights!\n')

        if new_image.image_url and new_image.image_name:
            self.response.headers['Content-Type'] = 'image/jpeg'

            db_image = CrunchoImage.get_or_insert(new_image.image_name, name=new_image.image_name)

            if not db_image.blurred:
                new_image.blurred = check_image_for_blurring(new_image)

            if db_image.blurred == 'blurred':
                return self.response.write(get_thumbnail_image(new_image, db_image.original_url))

            if db_image.processed_url:
                logging.info("bucket_name: {}".format(new_image.bucket_name))
                logging.info("db_image.processed_url: {}".format(db_image.processed_url))
                if new_image.image_height and new_image.image_width:
                    return self.response.write(get_thumbnail_image(new_image, db_image.processed_url))
                return webapp2.redirect(str(db_image.processed_url))

            new_image.create_task_save_image
            update_image_in_bd(db_image, new_image)

            if not new_image.image_height and not new_image.image_width:
                new_image = get_image_size(new_image)
            return self.response.write(get_thumbnail_image(new_image, db_image.original_url))
        return self.response.write('\n\nNo file name or URL!\n')


class SaveImageOnStorage(webapp2.RequestHandler):
    def post(self):
        fields = {
            'quality': 'quality',
            'image_width': 'image_width',
            'image_height': 'image_height',
            'image_name': 'image_name',
            'image_url': 'image_url',
        }

        new_image = Filter(self.request, fields)

        blob = get_blob(new_image)
        image = get_image_by_url(new_image.image_url)
        logging.info("self.image_width: {}".format(new_image.image_width))
        logging.info("self.image_height: {}".format(new_image.image_height))
        if new_image.image_width and new_image.image_height:
            image = resize_image(image, new_image)
        image.im_feeling_lucky()
        jpeg = images.images_service_pb.OutputSettings.JPEG
        thumbnail = image.execute_transforms(output_encoding=jpeg, quality=new_image.quality)
        blob.upload_from_string(thumbnail, content_type='image/jpeg')


class UploadImageOnStorage(webapp2.RequestHandler):
    def get(self):
        self.response.headers.add_header('Access-Control-Allow-Origin', settings.ACCESS_CONTROL_ALLOW_ORIGIN)
        self.response.headers['Content-Type'] = 'text/plain'

        if self.request.headers.get('Host') not in settings.ACCESS_LIST:
            return self.response.write('\n\nYou do not have access rights!\n')

        fields = {
            'quality': 'quality',
            'image_width': 'image_width',
            'image_height': 'image_height',
            'image_name': 'image_name',
            'image_url': 'image_url',
        }

        new_image = Filter(self.request, fields)

        if self.request.headers.get('Host') not in settings.ACCESS_LIST:
            return self.response.write('\n\nYou do not have access rights!\n')

        if new_image.image_url and new_image.image_name:
            self.response.headers['Content-Type'] = 'image/jpeg'
            db_image = CrunchoImage.get_or_insert(new_image.image_name, name=new_image.image_name)
            blob = get_blob(new_image)
            update_image_in_bd(db_image, new_image)
            new_image.create_task_save_image

            return self.response.write(blob.public_url)
        return self.response.write('\n\nNo file name or URL!\n')


# class AdminPage(webapp2.RequestHandler):
#     def get(self):
#         user = users.get_current_user()
#         logging.info("user: {}".format(user))
#         if user:
#             logging.info("user auth: {}".format(user))
#             if users.is_current_user_admin():
#                 logging.info("is_current_user_admin: {}".format(users.is_current_user_admin()))
#                 self.response.write('You are an administrator.')
#             else:
#                 self.response.write('You are not an administrator.')
#         else:
#             self.response.write('You are not logged in.')
#
#
# class AuthPage(webapp2.RequestHandler):
#     def get(self):
#         # [START user_details]
#         user = users.get_current_user()
#         if user:
#             nickname = user.nickname()
#             logout_url = users.create_logout_url('/')
#             greeting = 'Welcome, {}! (<a href="{}">sign out</a>)'.format(
#                 nickname, logout_url)
#         else:
#             login_url = users.create_login_url('/')
#             greeting = '<a href="{}">Sign in</a>'.format(login_url)
#         # [END user_details]
#         self.response.write(
#             '<html><body>{}</body></html>'.format(greeting))


def check_image_for_blurring(new_image):
    thresh = 35
    MinZero = 0.03

    image_at_url = urllib2.urlopen(str(new_image.image_url))
    im = Image.open(image_at_url).convert('F')
    x = numpy.asarray(im)
    x_cropped = x[0:(numpy.shape(x)[0] / 16) * 16 - 1, 0:(numpy.shape(x)[1] / 16) * 16 - 1]
    LL1, (LH1, HL1, HH1) = dwt2(x_cropped, 'haar')
    LL2, (LH2, HL2, HH2) = dwt2(LL1, 'haar')
    LL3, (LH3, HL3, HH3) = dwt2(LL2, 'haar')
    Emap1 = numpy.square(LH1) + numpy.square(HL1) + numpy.square(HH1)
    Emap2 = numpy.square(LH2) + numpy.square(HL2) + numpy.square(HH2)
    Emap3 = numpy.square(LH3) + numpy.square(HL3) + numpy.square(HH3)

    dimx = numpy.shape(Emap1)[0] / 8
    dimy = numpy.shape(Emap1)[1] / 8
    Emax1 = []
    vert = 1
    for j in range(0, dimx - 2):
        horz = 1;
        Emax1.append([])
        for k in range(0, dimy - 2):
            Emax1[j].append(numpy.max(numpy.max(Emap1[vert:vert + 7, horz:horz + 7])))
            horz = horz + 8
        vert = vert + 8

    dimx = numpy.shape(Emap2)[0] / 4
    dimy = numpy.shape(Emap2)[1] / 4
    Emax2 = []
    vert = 1
    for j in range(0, dimx - 2):
        horz = 1;
        Emax2.append([])
        for k in range(0, dimy - 2):
            Emax2[j].append(numpy.max(numpy.max(Emap2[vert:vert + 3, horz:horz + 3])))
            horz = horz + 4
        vert = vert + 4

    dimx = numpy.shape(Emap3)[0] / 2
    dimy = numpy.shape(Emap3)[1] / 2
    Emax3 = []
    vert = 1
    for j in range(0, dimx - 2):
        horz = 1;
        Emax3.append([])
        for k in range(0, dimy - 2):
            Emax3[j].append(numpy.max(numpy.max(Emap3[vert:vert + 1, horz:horz + 1])))
            horz = horz + 2
        vert = vert + 2

    N_edge = 0
    N_da = 0
    N_rg = 0
    N_brg = 0

    EdgeMap = []
    for j in range(0, dimx - 2):
        EdgeMap.append([])
        for k in range(0, dimy - 2):
            if (Emax1[j][k] > thresh) or (Emax2[j][k] > thresh) or (Emax3[j][k] > thresh):
                EdgeMap[j].append(1)
                N_edge = N_edge + 1
                rg = 0
                if (Emax1[j][k] > Emax2[j][k]) and (Emax2[j][k] > Emax3[j][k]):
                    N_da = N_da + 1
                elif (Emax1[j][k] < Emax2[j][k]) and (Emax2[j][k] < Emax3[j][k]):
                    rg = 1
                    N_rg = N_rg + 1
                elif (Emax2[j][k] > Emax1[j][k]) and (Emax2[j][k] > Emax3[j][k]):
                    rg = 1
                    N_rg = N_rg + 1
                if rg and (Emax1[j][k] < thresh):
                    N_brg = N_brg + 1
            else:
                EdgeMap[j].append(0)

    per = float(N_da) / N_edge
    BlurExtent = float(N_brg) / N_rg
    logging.info("per: {}".format(per))
    if per > MinZero:
        blurred = "not blurred"
        logging.info("Not blurred")
    else:
        blurred = "blurred"
        logging.info("Blurred")
    logging.info("BlurExtent: {}".format(str(BlurExtent)))
    return blurred

app = webapp2.WSGIApplication([
    ('/img', MainPage),
    ('/upload_image', UploadImageOnStorage),
    ('/save_image', SaveImageOnStorage)
    # ('/admin', AdminPage),
    # ('/auth', AuthPage),
], debug=True)

# webapp = webapp2.WSGIApplication([
#     ('/img', MainPage),
#     ('/admin', AdminPage),
#     ('/auth', AuthPage),
#     ('/save_image', SaveImageOnStorage)
# ], debug=True)
#
# app = CorsApplication(webapp, CorsOptions(allow_origins=['cruncho.com'],
#                                           allow_headers=['X-Foo'],
#                                           continue_on_error=True))
