import urllib.request
url='http://127.0.0.1:5003/api'
req=urllib.request.Request(url, headers={'User-Agent':'test'})
with urllib.request.urlopen(req) as resp:
    print('URL:', url)
    print('Status:', resp.status)
    data=resp.read(400)
    print('Body:', data.decode('utf-8', errors='replace'))
