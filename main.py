import logging
import urllib2
import webapp2
import settings

from google.appengine.api import images, taskqueue
from google.cloud.storage import Client
from google.appengine.ext import db

from requests_toolbelt.adapters import appengine

appengine.monkeypatch()


def get_storage_client():
    return Client(project=settings.PROJECT_NAME)


def check_image_by_url(url):
    error = False
    error_data = None
    try:
        image_at_url = urllib2.urlopen(url)
    except (Exception, TypeError, ValueError) as e:
        error = True
        error_data = e
    return error, error_data


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
    logging.info("get_image_size")
    img = get_image_by_url(new_image.image_url)
    new_image.image_width = img.width
    new_image.image_height = img.height
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
    created = db.DateTimeProperty(auto_now_add=True)


class Filter(object):
    def __init__(self, view, fields):
        self.view = view
        for name, key in fields.items():
            if key == 'image_width' or key == 'image_height':
                setattr(self, name, view.get(key))
            elif key == 'image_name':
                setattr(self, name, view.get(key, view.get('image_url')))
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

        #        if self.request.headers.get('Host') not in settings.ACCESS_LIST:
        #        	return self.response.write('\n\nYou do not have access rights!\n')

        if new_image.image_url and new_image.image_name:
            error, error_data = check_image_by_url(new_image.image_url)
            if error:
                return self.response.write('\n\nError %s!\n' % error_data)
            try:
                self.response.headers['Content-Type'] = 'image/jpeg'
                db_image = CrunchoImage.get_or_insert(new_image.image_name, name=new_image.image_name)

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
            except (Exception, TypeError, ValueError) as e:
                return self.response.write('\n\nError %s!\n' % e)
            return self.response.write('\n\nNo file name or URL!\n')
        return self.response.write('\n\nReceived incorrect data!\n')


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
            error, error_data = check_image_by_url(new_image.image_url)
            if error:
                return self.response.write('\n\nError %s!\n' % error_data)
            self.response.headers['Content-Type'] = 'image/jpeg'
            db_image = CrunchoImage.get_or_insert(new_image.image_name, name=new_image.image_name)
            blob = get_blob(new_image)
            update_image_in_bd(db_image, new_image)
            new_image.create_task_save_image

            return self.response.write(blob.public_url)

        return self.response.write('\n\nReceived incorrect data!\n')


app = webapp2.WSGIApplication([
    ('/img', MainPage),
    ('/upload_image', UploadImageOnStorage),
    ('/save_image', SaveImageOnStorage)
], debug=True)
