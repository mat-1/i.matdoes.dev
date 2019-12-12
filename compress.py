import zlib, struct

header = b'\x89PNG\r\n\x1A\n'

def png(bytes):

	assert bytes.startswith(header)

	output = header

	original_bytes = bytes
	bytes = bytes[len(header):]

	idat_max_length = 256
	entire_idat = b''


	stuff = []

	while bytes != b'':
		chunk_length = struct.unpack('>I', bytes[:4])[0]
		bytes = bytes[4:]
		chunk_type = bytes[:4]
		bytes = bytes[4:]
		chunk_data = bytes[:chunk_length]
		bytes = bytes[chunk_length:]
		crc = bytes[:4]
		bytes = bytes[4:]
		if chunk_type in [b'IHDR', b'PLTE', b'IDAT', b'IEND']:
			if chunk_type == b'IDAT':
				if chunk_length > idat_max_length:
					idat_max_length = chunk_length
				entire_idat += chunk_data
			else:
				stuff.append((chunk_length, chunk_type, chunk_data, crc))

	for chunk in stuff:
		chunk_length, chunk_type, chunk_data, crc = chunk
		if chunk_type == b'IEND': # put idat right before iend
			recompressed = zlib.compress(zlib.decompress(entire_idat), level=9)
			# recompressed = entire_idat
			idat_new_chunks = list(recompressed[i:i+idat_max_length] for i in range(0, len(recompressed), idat_max_length))
			for c in idat_new_chunks:
				idat_crc = struct.pack('>I', zlib.crc32(b'IDAT' + c))
				output += struct.pack('>I', len(c))
				output += b'IDAT'
				output += c
				output += idat_crc
			output += b'\x00\x00\x00\ntEXtAuthor\x00mat\xbch\xa4\xde\x00\x00\x00\x1dtEXtCopyright\x00(c) matdoesdev 2019\x7fW\xa9W\x00\x00\x00\x18tEXtSoftware\x00pure python boi\x07FM*\x00\x00\x00\x16tEXtSource\x00https://imag.cf.\x05\xe5\x9b'
			output += b'\x00\x00\x00\x00IEND\xaeB`\x82'
			return output
		else:
			output += struct.pack('>I', chunk_length)
			output += chunk_type
			output += chunk_data
			output += crc
