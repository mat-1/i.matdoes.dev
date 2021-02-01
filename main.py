import setup
from aiohttp import web
import hashlib
import pymongo.errors
import os
import psutil
import asyncio
import time
import json
from jinja2 import Environment, \
	FileSystemLoader, \
	select_autoescape
from base64 import b64encode
import database as db
import binascii
import secrets
import compress
import pcompress

banned_phrases = os.getenv('banned_phrases').split(',') # phrases that can't appear in short links

base_url = 'https://i.matdoes.dev'

print('initializing...')

loop = asyncio.get_event_loop()

routes = web.RouteTableDef()

jinja_env = Environment(
	loader=FileSystemLoader(searchpath='templates'),
	autoescape=select_autoescape(['html', 'xml']),
	enable_async=True,
	lstrip_blocks=True,
	trim_blocks=True,
)

class templates:
	template_dict = {}

uptime = time.time()

async def load_template(filename, **kwargs):
	if filename in templates.template_dict:
		r =	await templates.template_dict[filename].render_async(**kwargs)
	else:
		print(f'Loading template {filename} for the first time')
		t = jinja_env.get_template(filename)
		templates.template_dict[filename] = t
		r = await t.render_async(**kwargs)
	return r


p = psutil.Process(os.getpid())
print('ree starting')


def get_memory_usage():
	mem = p.memory_info().rss
	return mem / 1024 / 1024

def get_cpu_usage():
	cpu = p.cpu_percent()
	return cpu

class performance:
	images = 0
	views = 0
	bot_views = 0
	async def get_perf(self):
		while True:
			self.memory = get_memory_usage()
			self.cpu = get_cpu_usage()
			await asyncio.sleep(1)
	async def init(self, app):
		print('started memory usage tracker')
		asyncio.ensure_future(self.get_perf())

perf = performance()

image_count = 0
perf.images = image_count

max_im_len = 1000000


@web.middleware
async def middleware(request, handler):
	perf.views += 1
	
	resp = await handler(request)
	headers = request.headers
	if 'user-agent' in headers:
		print(f'{request.path} has been viewed by', headers['user-agent'])
	else:
		print(f'{request.path} has been viewed by an unknown user', headers)
		return web.HTTPError('Error: No UA found')
	# if ''
	if resp.content_type == 'text/html':
		try:
			resp.text = resp.text.replace('[[PATH]]', request.path)
		except AttributeError:
			pass
	return resp

@web.middleware
async def short_im(request, handler):
	try:
		resp = await handler(request)
	except web.HTTPNotFound as e:
		print(e, request.url)
		image = await db.images.find_one({
			'short': request.path[1:]
		})
		# print(image)
		print(request.match_info)
		# image = request.match_info['hex']
		# print('creating short link', image)
		return await show_image(image)
	except web.HTTPException as e:
		print(e)
		raise e
	else:
		return resp


@routes.get('/')
async def index(request):
	r = await load_template('index.html')
	return web.Response(
		text=r,
		headers={
			'content-type': 'text/html'
		}
	)

@routes.get('/api/docs')
async def api_docs(request):
	r = await load_template('api.html')
	return web.Response(
		text=r,
		headers={
			'content-type': 'text/html'
		}
	)

@routes.get('/view/{hex}')
async def view_image(request):
	im_hash = request.match_info['hex']
	if '.' in im_hash:
		im_hash, _ = im_hash.split('.', 1)
	i = await db.images.find_one({'_id': im_hash})
	if i is None:
		return web.HTTPNotFound(
			body='Not found',
			headers={
				'content-type': 'text/html'
			}
		)
	im_data = i['data']
	if im_data == None:
		return web.HTTPGone(
			body='This image has been removed',
			headers={
				'content-type': 'text/html'
			}
		)
	
	return web.Response(
		body=await load_template('view.html', id=im_hash, pic=i),
		headers={
			'content-type': 'text/html'
		}
	)



@routes.get('/json/{hex}')
async def get_json_data(request):
	im_hash = request.match_info['hex']
	if '.' in im_hash:
		im_hash, _ = im_hash.split('.', 1)
	i = await db.images.find_one({'_id': im_hash})
	if i is None:
		return web.HTTPNotFound(
			body='Not found',
			headers={
				'content-type': 'text/html'
			}
		)
	im_data = i['data']
	if im_data == None:
		return web.HTTPGone(
			body='This image has been removed',
			headers={
				'content-type': 'text/html'
			}
		)
	i_serialized = {}
	if 'thumbnail' in i:
		if not i['thumbnail']:
			await show_image_thumbnail(i)
		i_serialized['thumbnail_b64'] = b64encode(i['thumbnail']).decode()
	else:
		try:
			await show_image_thumbnail(i)
		except OSError:
			pass
	for k in i:
		if isinstance(i[k], bytes):
			i_serialized[k] = f'<{len(i[k])} bytes>'
		else:
			i_serialized[k] = i[k]
	if 'password' in i_serialized:
		i_serialized['password'] = '[redacted]'
	json_data = json.dumps(i_serialized, indent=4)
	return web.Response(
		body=json_data,
		headers={
			'content-type': 'application/json'
		}
	)


@routes.get('/b64/{hex}')
async def get_b64_data(request):
	im_hash = request.match_info['hex']
	if '.' in im_hash:
		im_hash, _ = im_hash.split('.', 1)
	i = await db.images.find_one({'_id': im_hash})
	if i is None:
		return web.HTTPNotFound(
			body='Not found',
			headers={
				'content-type': 'text/html'
			}
		)
	im_data = i['data']
	if im_data == None:
		return web.HTTPGone(
			body='This image has been removed',
			headers={
				'content-type': 'text/html'
			}
		)
	return web.Response(
		body=b64encode(im_data).decode()
	)

async def delete_old_images(app):
	return asyncio.ensure_future(delete_old_images_task(app))
async def delete_old_images_task(app):
	while True:
		deleted_count = 0
		search_before = time.time() - 31557600 # a year
		r = await db.images.delete_many({
			'last-view': {'$lt': search_before},
			'data': {'$ne': None}
		})
		# deleted_count += r.deleted_count
		# search_before = time.time() - 3600 # an hour
		# r = await db.images.delete_many({
		# 	'last-view': {'$lt': search_before},
		# 	'views': {'$lte': 1},
		# 	'data': {'$ne': None},
		# 	'length': {'$gt': 10000}
		# })
		# deleted_count += r.deleted_count
		# search_before = time.time() - 604800 # a week
		# r = await db.images.delete_many({
		# 	'last-view': {'$lt': search_before},
		# 	'views': {'$lt': 10},
		# 	'data': {'$ne': None},
		# 	'length': {'$gt': 2000}
		# })
		# deleted_count += r.deleted_count
		# search_before = time.time() - 2629746 # a month
		# r = await db.images.delete_many({
		# 	'last-view': {'$lt': search_before},
		# 	'views': {'$lt': 30},
		# 	'data': {'$ne': None}
		# })
		# deleted_count += r.deleted_count
		# if deleted_count > 0:
		# 	print('deleted', deleted_count, 'images')
		# perf.images -= deleted_count
		# await asyncio.sleep(3600)

async def compress_old_images(app):
	return asyncio.ensure_future(compress_old_images_task(app))

async def compress_image(doc):
	try:
		if doc['content-type'] != 'image/jpeg':
			new_data = await loop.run_in_executor(None, pcompress.change_format, doc['data'], 'jpeg')
			doc['content-type'] = 'image/jpeg'
			doc['data'] = new_data
		else:
			if doc['width'] * doc['height'] > 10000:
				new_size = max((doc['width'], doc['height'])) * .9
				ratio = min(new_size / doc['width'], new_size / doc['height'])
				new_data = await loop.run_in_executor(None, pcompress.resize, doc['data'], new_size)
				doc['width'], doc['height'] = int(doc['width'] * ratio), int(doc['height'] * ratio)
			else:
				if 'jpeg-compression' in doc:
					jpeg_compression = doc['jpeg-compression'] - 5
				else:
					jpeg_compression = 50
				new_data = await loop.run_in_executor(None, pcompress.change_format, doc['data'], 'jpeg', jpeg_compression)
				doc['content-type'] = 'image/jpeg'
				doc['data'] = new_data
				doc['jpeg-compression'] = jpeg_compression
	except binascii.Error:
		print('binascii error compressing :(')
		return
	except RuntimeError:
		print('RuntimeError compressing :(')
		return
	old_length = doc['length']
	doc['data'] = new_data
	doc['length'] = len(new_data)
	await db.images.find_one_and_replace(
		{'_id': doc['_id']},
		doc
	)
	print('Saved', old_length - doc['length'], 'bytes')


async def compress_many(match):
	r = db.images.find(match)
	async for doc in r:
		if len(doc['data']) == 0:
			await db.images.delete_one({'_id': doc['_id']})
		else:
			await compress_image(doc)


async def compress_old_images_task(app):
	async for doc in db.images.find({
		'last-view': {'$lt': time.time() - 120}, # if an image hasnt been viewed in 2 minutes and it hasnt done the normal jpeg compression, do that
		'json-compression': {'$exists': False},
		'content-type': 'image/jpeg'
	}):
		jpeg_compression = 50
		new_data = await loop.run_in_executor(None, pcompress.change_format, doc['data'], 'jpeg', jpeg_compression)
		doc['content-type'] = 'image/jpeg'
		doc['data'] = new_data
		doc['jpeg-compression'] = jpeg_compression
		await db.images.find_one_and_replace(
			{'_id': doc['_id']},
			doc
		)


	search_max_time = 604800 # a week
	while search_max_time > 86400 * 24:
		search_before = time.time() - search_max_time
		await compress_many({
			'last-view': {'$lt': search_before},
			'data': {'$ne': None}
		})
		search_max_time -= 3600


async def add_one_view(im_hash):
	await db.images.update_one(
		{'_id': im_hash},
		{
			'$inc': {'views': 1},
			'$set': {'last-view': time.time()}
		}
	)

async def show_image(i):
	if i is None:
		return web.HTTPNotFound(
			body='Not found, image is None',
			headers={
				'content-type': 'text/html'
			}
		)
	im_data = i['data']
	if im_data == None:
		return web.HTTPGone(
			body='This image has been removed',
			headers={
				'content-type': 'text/html'
			}
		)
	
	asyncio.get_event_loop().create_task(add_one_view(i['_id']))

	if not 'content-type' in i:
		return web.Response(
			text='No content type found'
		)
	return web.Response(
		body=im_data,
		content_type=i['content-type'],
		headers={
			'Cache-Control': 'max-age=86400'
		}
	)

async def show_image_thumbnail(doc):
	if doc is None:
		return web.HTTPNotFound(
			body='Not found, image is None',
			headers={
				'content-type': 'text/html'
			}
		)
	im_thumbnail = doc.get('thumbnail')
	if im_thumbnail == None:
		if doc['data']:
			thumbnail_bytes = await loop.run_in_executor(
				None, pcompress.webp_compress, doc['data']
			)
			await db.images.update_one(
				{'id': doc['id']},
				{'$set': {
					'thumbnail': thumbnail_bytes,
					'thumbnail-content-type': 'image/webp',
				}}
			)
			im_thumbnail = thumbnail_bytes
		else:
			return web.HTTPGone(
				body='This image has been removed',
				headers={
					'content-type': 'text/html'
				}
			)

	
	if not 'content-type' in doc:
		return web.Response(
			text='No content type found'
		)
	return web.Response(
		body=im_thumbnail,
		content_type=doc.get('thumbnail-content-type', 'image/webp')
	)

@routes.get('/image/{hex}')
async def get_image_view(request):
	im_hash = request.match_info['hex']
	if '.' in im_hash:
		im_hash, _ = im_hash.split('.', 1)
	i = await db.images.find_one({'_id': im_hash})
	return await show_image(i)

@routes.get('/image/{hex}/thumbnail')
async def get_image_thumbnail_view(request):
	im_hash = request.match_info['hex']
	if '.' in im_hash:
		im_hash, _ = im_hash.split('.', 1)
	i = await db.images.find_one({'_id': im_hash})
	return await show_image_thumbnail(i)

	

@routes.get('/performance')
async def get_performance(request):
	r = await load_template(
		'performance.html'
	)
	return web.Response(
		text=r,
		headers={
			'content-type': 'text/html'
		}
	)

@routes.get('/performance/ws')
async def get_performance_ws(request):
	print('Connected to ws')
	ws = web.WebSocketResponse()
	await ws.prepare(request)
	while True:
		uptime_int = int(time.time() - uptime)
		uptime_str = ''
		uptime_list = []
		d = int(uptime_int / 86400)
		h = int(uptime_int / 3600)
		m = int(uptime_int / 60)
		s = int(uptime_int)
		if d > 0:
			uptime_list.append(str(h) + 'd')
		if h > 0:
			uptime_list.append(str(h % 24) + 'h')
		if m > 0:
			uptime_list.append(str(m % 60) + 'm')
		uptime_list.append(str(s % 60) + 's')
		for t in uptime_list[:-1]:
			uptime_str += t + ', '
		uptime_str += uptime_list[-1]
		usage = {
			'mem': perf.memory,
			'cpu': perf.cpu,
			'uptime': uptime_str,
			'views': perf.views,
			'images': perf.images
		}
		await ws.send_str(json.dumps(usage))
		await asyncio.sleep(1)

class NotAnImageError(Exception):pass
class TooLargeError(Exception):pass

async def compress_png(doc):
	loop = asyncio.get_event_loop()
	if doc['content-type'].startswith('image/png'):
		new_bytes = await loop.run_in_executor(
			None, compress.png, doc['data']
		)
		if len(new_bytes) < len(doc['data']):
			print('png compressed', len(doc['data']), 'bytes to', len(new_bytes), 'bytes')
			# doc['data'] = new_bytes
			# print('id:', doc['id'])
			await db.images.update_one(
				{'id': doc['id']},
				{'$set': {
					'data': new_bytes,
					'length': len(new_bytes)
				}}
			)
			doc['data'] = new_bytes
		
	thumbnail_bytes = await loop.run_in_executor(
		None, pcompress.webp_compress, doc['data']
	)
	await db.images.update_one(
		{'id': doc['id']},
		{'$set': {
			'thumbnail': thumbnail_bytes,
			'thumbnail-content-type': 'image/webp',
		}}
	)
	

async def upload_image(im_bytes, content_type, short_url=None):
	if not content_type.startswith('image/'):
		print(content_type)
		raise NotAnImageError('Invalid content type')
	hash_md5 = hashlib.md5()
	if len(im_bytes) >= max_im_len: # if image is larger than 1mb then convert to jpeg
		print('compressing large image when uploading')
		try:
			if content_type == 'image/gif':
				new_data = await loop.run_in_executor(None, pcompress.resize, im_bytes, 100, True)
			else:
				new_data = await loop.run_in_executor(None, pcompress.change_format, im_bytes, 'jpeg', 100)
				content_type = 'image/jpeg'
		except Exception as e:
			print('error on compressing large image', type(e), e)
			new_data = im_bytes
		if len(new_data) >= max_im_len: # 1mb
			raise TooLargeError('Image is too large :(')
		else:
			print('Successfully compressed large image!',len(im_bytes),'bytes to',len(new_data),'bytes.')
			im_bytes = new_data
	print('image with',len(im_bytes),'bytes recieved')
	# time1 = time.time()
	hash_md5.update(im_bytes)
	im_hash = hash_md5.hexdigest()
	# time2 = time.time()
	# print('Took', time2-time1, 'seconds to generate md5 hash')
	# print(im_hash, im_bytes)
	im_password = secrets.token_hex(16)
	image_width, image_height = pcompress.get_image_size(im_bytes)
	try:
		document = {
			'id': im_hash,
			'data': im_bytes,
			'content-type': content_type,
			'views': 0,
			'last-view': time.time(),
			'short': short_url,
			'password': im_password,
			'length': len(im_bytes),
			'thumbnail': None,
			'thumbnail-content-type': None,
			'width': image_width,
			'height': image_height
		}
		# time1 = time.time()
		await db.images.update_one(
			{'_id': im_hash},
			{'$set': document},
			upsert=True
		)
		# time2 = time.time()
		# print('Took', time2-time1,'seconds to set image')

		perf.images += 1
		asyncio.ensure_future(compress_png(document))
	except pymongo.errors.DuplicateKeyError:
		print('duplicate key')
	return im_hash, im_password

@routes.post('/')
async def upload_image_manual(request):
	data = await request.post()
	print(data)
	image = data['image']
	content_type = image.content_type
	im_bytes = image.file.read()
	try:
		im_hash, im_password = await upload_image(im_bytes, content_type)
	except NotAnImageError:
		return web.Response(
			text=f'Error, <code>Content-Type: {content_type}</code> is not an image.',
			headers={
				'content-type': 'text/html'
			}
		)
	except TooLargeError:
		return web.Response(
			text=f'Image is too large :(',
			headers={
				'content-type': 'text/html'
			}
		)

	return web.HTTPFound(
		'/view/'+ im_hash
	)

@routes.post('/api/upload/short')
async def api_upload_short(request):
	data = await request.post()
	image = data['image']
	content_type = image.content_type
	im_bytes = image.file.read()
	short_url = await generate_short_url()
	try:
		im_hash, im_password = await upload_image(im_bytes, content_type, short_url=short_url)
	except TooLargeError:
		return web.HTTPRequestEntityTooLarge(max_size=max_im_len, actual_size=len(im_bytes))
	return web.json_response(
		{
			'url': f'{base_url}/{short_url}',
			'raw': f'{base_url}/image/{im_hash}',
			'shortkey': short_url,
			'view': f'{base_url}/view/{im_hash}',
			'password': im_password,
			'delete': f'{base_url}/api/delete/{im_password}',
		}
	)



@routes.post('/api/upload')
async def api_upload(request):
	data = await request.post()
	image = data['image']
	content_type = image.content_type
	start_time = time.time()
	im_bytes = image.file.read()
	end_time = time.time()
	print('spent', float(end_time - start_time), 'seconds reading file from api')
	try:
		im_hash, im_password = await upload_image(im_bytes, content_type)
	except TooLargeError:
		return web.HTTPRequestEntityTooLarge(max_size=max_im_len, actual_size=len(im_bytes))
	return web.json_response(
		{
			'hash': im_hash,
			'url': f'{base_url}/image/{im_hash}',
			'view': f'{base_url}/view/{im_hash}',
			'password': im_password,
			'delete': f'{base_url}/api/delete/{im_password}',
		}
	)

async def generate_short_url():
	chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
	min_length = 5
	url = ''.join(secrets.choice(chars) for _ in range(min_length-1))
	for _ in range(100):
		url += secrets.choice(chars)
		for b in banned_phrases:
			if b in url:
				url = ''.join(secrets.choice(chars) for _ in range(min_length))
		if await db.images.find_one({'short': url}) is None:
			break
	return url

async def shorten_link(im_hash, check_already_short):
	if check_already_short:
		im_data = await db.images.find_one({'_id': im_hash})
		if im_data is None:
			raise web.HTTPNotFound()
		is_shortened = 'short' in im_data
		if is_shortened:
			if im_data['short'] is None:
				is_shortened = False
	else:
		is_shortened = False

	if is_shortened:
		short_url = im_data['short']
	else:
		print('generating short url')
		short_url = await generate_short_url()
		print(short_url)
		await db.images.update_one(
			{'_id': im_hash},
			{'$set':
				{'short': short_url}
			},
			upsert=False)
	return short_url

@routes.get('/api/shorten/{hex}')
async def shorten_link_manual(request):
	im_hash = request.match_info['hex']
	short_url = await shorten_link(im_hash, True)
	return web.Response(
		text=short_url
	)


@routes.get('/api/delete/{password}')
async def delete_im_from_pass(request):
	im_password = request.match_info['password']
	r = await db.images.delete_one({'password': im_password})
	
	return web.Response(
		text='ok' if r.deleted_count else 'nothing got deleted'
	)


@routes.get('/api/compress/{password}')
async def compress_im_from_pass(request):
	im_password = request.match_info['password']
	doc = await db.images.find_one({'password': im_password})
	await compress_image(doc)
	
	return web.Response(
		text='ok'
	)




async def count_documents(app):
	image_count = await db.images.count_documents({})
	perf.images = image_count


app = web.Application(middlewares=[short_im, middleware], client_max_size=4096**2)
app.add_routes(routes)
app.add_routes([web.static('/', 'website')])
app.on_startup.append(perf.init)
app.on_startup.append(delete_old_images)
app.on_startup.append(compress_old_images)
app.on_startup.append(count_documents)
web.run_app(app)
