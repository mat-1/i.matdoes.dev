import io
from PIL import Image

def resize_animated(image_data, size):
	print('opened bytes')
	im = Image.open(io.BytesIO(image_data))
	frames = []
	while True:
		im_tell = im.tell()
		print(im_tell)
		try:
			im.seek(im_tell + 1)
		except EOFError:
			break
		frame_data = resize(im, size)
		frame = Image.open(io.BytesIO(frame_data))
		frames.append(frame)
	with io.BytesIO() as output:
		frames[0].save(output, format='gif', save_all=True, append_images=frames[1:])
		contents = output.getvalue()
	print('ok')
	return contents

def resize(image_data, size, is_animated=False):
	if is_animated:
		print('resizing animated')
		return resize_animated(image_data, size)
	try:
		if isinstance(image_data, (bytes, bytearray)):
			im = Image.open(io.BytesIO(image_data))
		else:
			im = image_data
		ratio = min(size / im.width, size / im.height)
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

# thumbnails
def webp_compress(image_data, max_size=32, quality=0):
	im = Image.open(io.BytesIO(image_data))
	ratio = min(max_size / im.width, max_size / im.height)
	new_size = (im.width * ratio, im.height * ratio)
	im.thumbnail(new_size, Image.ANTIALIAS)

	with io.BytesIO() as output:
		im.save(output, format='webp', quality=quality, method=6)
		contents = output.getvalue()
	return contents

def get_image_size(image_data):
	im = Image.open(io.BytesIO(image_data))
	width, height = im.size
	return (width, height)