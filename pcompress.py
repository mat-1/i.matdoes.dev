import io
from PIL import Image

def resize(image_data, size):
	try:
		im = Image.open(io.BytesIO(image_data))
		ratio = min(size / im.width, size / im.height)
		print(im.size)
		new_size = (im.width * ratio, im.height * ratio)
		im.thumbnail(new_size, Image.ANTIALIAS)
		with io.BytesIO() as output:
			im.save(output, format=im.format)
			contents = output.getvalue()
		return contents
	except OSError:
		return b''

def change_format(image_data, im_format, quality=50):
	im = Image.open(io.BytesIO(image_data))
	with io.BytesIO() as output:
		im = im.convert('RGB')
		im.save(output, format=im_format, quality=quality)
		contents = output.getvalue()
	return contents