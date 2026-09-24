import asyncio
from main import run_pipeline
from PIL import Image, ImageDraw
import io
import numpy as np

# Create an image that the model will interpret as an oil spill.
# A white background with a dark ellipse/blob in the center.
img_array = np.full((256, 256), 200, dtype=np.uint8)
img = Image.fromarray(img_array)
draw = ImageDraw.Draw(img)
draw.ellipse((80, 80, 180, 140), fill=20) # A dark blob resembling a spill

byte_io = io.BytesIO()
img.save(byte_io, 'PNG')
image_bytes = byte_io.getvalue()

result = run_pipeline(image_bytes=image_bytes)
import json
print(json.dumps(result, indent=2))
