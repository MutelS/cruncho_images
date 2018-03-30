import logging
import urllib2
import webapp2
import settings

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
    im = Image.open(image_at_url)
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


class Cruncho_Image(db.Model):
    name = db.StringProperty()
    original_url = db.StringProperty()
    processed_url = db.StringProperty()
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
        }

        new_image = Filter(self.request, fields)

        if self.request.headers.get('Host') not in settings.ACCESS_LIST:
            return self.response.write('\n\nYou do not have access rights!\n')

        if new_image.image_url and new_image.image_name:
            self.response.headers['Content-Type'] = 'image/jpeg'
            db_image = Cruncho_Image.get_or_insert(new_image.image_name, name=new_image.image_name)

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
            db_image = Cruncho_Image.get_or_insert(new_image.image_name, name=new_image.image_name)
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


app = webapp2.WSGIApplication([
    ('/img', MainPage),
    ('/upload_image', UploadImageOnStorage)
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
