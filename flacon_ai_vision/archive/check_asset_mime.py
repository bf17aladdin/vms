import urllib.request
url='http://127.0.0.1:5003/assets/index-rR2--ZSn.js'
req=urllib.request.Request(url, headers={'User-Agent':'test'})
with urllib.request.urlopen(req) as resp:
    print('URL:', url)
    print('Status:', resp.status)
    print('Content-Type:', resp.getheader('Content-Type'))
    data=resp.read(64)
    print('Starts with:', data[:64])
