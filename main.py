import logging
import os
import urllib2

import webapp2
from google.appengine.api import images, files
from google.appengine.api.images import images_service_pb
import lib.google.cloud.storage as storage

from requests_toolbelt.adapters import appengine
appengine.monkeypatch()


class MainPage(webapp2.RequestHandler):

    bucket_name = None

    def save_image(self, image_url, image_name):
        client = self.get_storage_client()

        bucket = client.bucket(self.bucket_name)
        blob = bucket.blob(image_name)
        image_at_url = urllib2.urlopen(image_url)
        image_bytes = image_at_url.read()

        image = images.Image(image_bytes)
        image.im_feeling_lucky()

        url = blob.public_url
        blob_key = files.blobstore.get_blob_key('/blobstore/' + image_name)
        logging.info("blob_key: {}".format(blob_key))

        jpeg = images_service_pb.OutputSettings.JPEG
        thumbnail = image.execute_transforms(output_encoding=jpeg)
        blob.upload_from_string(thumbnail, content_type='image/jpeg')
        logging.info("url: {}".format(url))
        image_at_url.close()

        logging.info("url decode: {}".format(url))

    def get_storage_client(self):
        return storage.Client(project='cruncho-images')

    # [START get_default_bucket]
    def get(self):
        self.bucket_name = 'cruncho-images.appspot.com'
        self.response.headers['Content-Type'] = 'text/plain'
        image_name = self.request.get('image_name')
        image_url = self.request.get('image_url')

        if image_url and image_name:
            image_name = self.request.get('image_name')

            client = self.get_storage_client()

            bucket = client.bucket(self.bucket_name)
            blob = bucket.get_blob(image_name)

            if blob:
                url = blob.public_url
            else:
                blob = bucket.blob(image_name)
                url = blob.public_url
                self.save_image(image_url, image_name)
            return self.response.write(url)
        else:
            return self.response.write('\n\nNo file name or URL!\n')


app = webapp2.WSGIApplication([('/', MainPage)],
                              debug=True)
