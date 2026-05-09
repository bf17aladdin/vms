import urllib.request
import urllib.error
import json

def fetch(path, method='GET', data=None):
    url = 'http://127.0.0.1:5001/' + path
    req = urllib.request.Request(url, method=method)
    if data is not None:
        body = json.dumps(data).encode('utf-8')
        req.add_header('Content-Type', 'application/json')
        req.data = body
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
            ct = resp.getheader('Content-Type')
            return resp.getcode(), ct, content
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('Content-Type'), e.read()
    except Exception as e:
        return None, None, str(e).encode('utf-8')

if __name__ == '__main__':
    tests = ['/docs', '/openapi.json', '/api/test/camera/start', '/api/test/camera/status']
    for p in tests:
        if p == '/api/test/camera/start':
            code, ct, body = fetch(p, method='POST')
        else:
            code, ct, body = fetch(p)
        print('PATH:', p)
        print('STATUS:', code)
        print('CONTENT-TYPE:', ct)
        if ct and 'application/json' in ct:
            try:
                j = json.loads(body)
                print('JSON:', json.dumps(j, indent=2, ensure_ascii=False)[:1000])
            except Exception as e:
                print('JSON parse error:', e)
        else:
            # print a short snippet of HTML or text
            snippet = body.decode('utf-8', errors='replace')
            print('BODY_SNIPPET:', snippet[:1000])
        print('\n' + '-'*60 + '\n')
