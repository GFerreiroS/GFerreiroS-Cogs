import os

from openai import OpenAI

XAI_API_KEY = "xai-TL5cFDGERUHXe2zYNFl3YYK6Q81GPJilOdZvsqEeSIhqCGNaO6SPUTnu8Eaho7UNAqr7c6zYN0mhHLWG"
client = OpenAI(base_url="https://api.x.ai/v1", api_key=XAI_API_KEY)

response = client.images.generate(
  model="grok-2-image",
  prompt="A cat in a tree"
)

print(response.data[0].url)