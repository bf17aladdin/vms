import glob, py_compile, sys
files = glob.glob('vms/backend/**/*.py', recursive=True)
errors = []
print(f'Found {len(files)} python files under vms/backend')
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print('OK ', f)
    except Exception as e:
        print('ERR', f, '->', e)
        errors.append((f, str(e)))
print('\nSummary:')
print('Total files:', len(files))
print('Errors:', len(errors))
if errors:
    for f, e in errors:
        print('-', f, e)
    sys.exit(2)
print('All good')
sys.exit(0)
