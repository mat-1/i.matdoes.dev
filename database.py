import os
import motor.motor_asyncio
import urllib.parse

dbuser = os.getenv('dbuser')
dbpassword = urllib.parse.quote_plus(os.getenv('dbpass'))

connection_string = f'mongodb+srv://{dbuser}:{dbpassword}@image-uploader-psbdr.mongodb.net/test?retryWrites=true&w=majority'
db = motor.motor_asyncio.AsyncIOMotorClient(connection_string)['image-uploader']

images = db.images
