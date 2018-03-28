import logging
import os
import urllib2

import webapp2
from google.appengine.api import images, files
from google.appengine.api.images import images_service_pb
from google.appengine.api import taskqueue
from google.cloud.storage import Client
from google.appengine.ext import db, blobstore
from google.appengine.api import users

from cors.cors_application import CorsApplication
from cors.cors_options import CorsOptions

from requests_toolbelt.adapters import appengine
appengine.monkeypatch()


class Image(db.Model):
  name = db.StringProperty()
  original_url = db.StringProperty()
  processed_url = db.StringProperty()
  created = db.DateTimeProperty(auto_now_add=True)


class MainPage(webapp2.RequestHandler):

    bucket_name = None

    def resize_image(self, image):
        image.resize(width=int(self.image_width), height=int(self.image_height))
        return image

    def get_storage_client(self):
        return Client(project='cruncho-images')

    def get_thumbnail_image(self, url):
        image_at_url = urllib2.urlopen(url)
        image_bytes = image_at_url.read()
        image = images.Image(image_bytes)
        img = images.get_serving_url(self.image_name)
        if self.image_height and self.image_width:
            image = self.resize_image(image)
        logging.info("img: {}".format(img))
        jpeg = images_service_pb.OutputSettings.JPEG
        thumbnail = image.execute_transforms(output_encoding=jpeg, quality=80)
        return thumbnail

    def get(self):
        self.response.headers.add_header('Access-Control-Allow-Origin', 'cruncho.com')
        logging.info("self.response: {}".format(self.response))
        logging.info("self.request: {}".format(self.request))
        self.bucket_name = 'cruncho-images.appspot.com'
        self.response.headers['Content-Type'] = 'text/plain'
        self.image_width = self.request.get('image_width')
        self.image_height = self.request.get('image_height')
        self.image_name = self.request.get('image_name')
        self.image_url = self.request.get('image_url')
        user = users.get_current_user()
        logging.info("user: {}".format(user))
        if user:
            logging.info("user auth: {}".format(user))
            if users.is_current_user_admin():
                logging.info("is_current_user_admin: {}".format(users.is_current_user_admin()))
        if self.image_url and self.image_name:
            self.response.headers['Content-Type'] = 'image/jpeg'
            keyname = self.image_name
            db_image = Image.get_or_insert(keyname, name=self.image_name)

            if db_image.processed_url:
                if self.image_height and self.image_width:
                    return self.response.write(self.get_thumbnail_image(db_image.processed_url))
                else:
                    return webapp2.redirect(str(db_image.processed_url))
            else:
                taskqueue.add(
                    url='/save_image',
                    params={'image_url': self.image_url,
                            'image_name': self.image_name,
                            'image_width': self.image_width,
                            'image_height': self.image_height,
                            'bucket_name': self.bucket_name})

                db_image.original_url = self.image_url
                client = self.get_storage_client()
                bucket = client.bucket(self.bucket_name)
                blob = bucket.blob(self.image_name)
                db_image.processed_url = blob.public_url
                db_image.save()

                logging.info("image: {}".format(db_image))
                logging.info("url: {}".format(self.image_url))
                logging.info("image.original_url: {}".format(db_image.original_url))
                logging.info("image.processed_url: {}".format(db_image.processed_url))
                return self.response.write(self.get_thumbnail_image(db_image.original_url))
        else:
            return self.response.write('\n\nNo file name or URL!\n')


class AdminPage(webapp2.RequestHandler):
    def get(self):
        user = users.get_current_user()
        logging.info("user: {}".format(user))
        if user:
            logging.info("user auth: {}".format(user))
            if users.is_current_user_admin():
                logging.info("is_current_user_admin: {}".format(users.is_current_user_admin()))
                self.response.write('You are an administrator.')
            else:
                self.response.write('You are not an administrator.')
        else:
            self.response.write('You are not logged in.')


class AuthPage(webapp2.RequestHandler):
    def get(self):
        # [START user_details]
        user = users.get_current_user()
        if user:
            nickname = user.nickname()
            logout_url = users.create_logout_url('/')
            greeting = 'Welcome, {}! (<a href="{}">sign out</a>)'.format(
                nickname, logout_url)
        else:
            login_url = users.create_login_url('/')
            greeting = '<a href="{}">Sign in</a>'.format(login_url)
        # [END user_details]
        self.response.write(
            '<html><body>{}</body></html>'.format(greeting))


class SaveImageOnStorage(webapp2.RequestHandler):

    def get_storage_client(self):
        return Client(project='cruncho-images')

    def resize_image(self, image):
        image.resize(width=int(self.image_width), height=int(self.image_height))
        return image

    def post(self):

        self.image_name = self.request.get('image_name')
        self.image_url = self.request.get('image_url')
        self.image_width = self.request.get('image_width')
        self.image_height = self.request.get('image_height')
        self.bucket_name = self.request.get('bucket_name')

        client = self.get_storage_client()
        bucket = client.bucket(self.bucket_name)
        blob = bucket.blob(self.image_name)

        image_at_url = urllib2.urlopen(self.image_url)
        image_bytes = image_at_url.read()
        image_at_url.close()

        image = images.Image(image_bytes)
        if self.image_width and self.image_height:
            image = self.resize_image(image)
        image.im_feeling_lucky()
        jpeg = images_service_pb.OutputSettings.JPEG
        thumbnail = image.execute_transforms(output_encoding=jpeg, quality=80)
        blob.upload_from_string(thumbnail, content_type='image/jpeg')

        logging.info("url decode: {}".format(blob.public_url))

app = webapp2.WSGIApplication([('/img', MainPage),
                               ('/admin', AdminPage),
                               ('/auth', AuthPage),
                               ('/save_image', SaveImageOnStorage)], debug=True)


# webapp = webapp2.WSGIApplication([
#     ('/img', MainPage),
#     ('/admin', AdminPage),
#     ('/auth', AuthPage),
#     ('/save_image', SaveImageOnStorage)
# ], debug=True)
#
# app = CorsApplication(webapp, CorsOptions(allow_origins=['crunchoo.com'],
#                                           allow_headers=['X-Foo'],
#                                           continue_on_error=True))
