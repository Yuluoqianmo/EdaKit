"""Read-only service benchmark. Credentials never appear in output."""
import argparse
import json
import statistics
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url-file',required=True,help='Private url.txt from the running EdaKit service')
    parser.add_argument('--samples',type=Path,help='JSON with keywords and cids; 30 distinct values recommended')
    parser.add_argument('--mode',choices=['cold','hot','upstream'],default='hot')
    args=parser.parse_args()
    base=Path(args.url_file).read_text(encoding='utf-8').strip().rstrip('/')
    samples=json.loads(args.samples.read_text(encoding='utf-8')) if args.samples else {'keywords':['RP2040'],'cids':['C2040']}
    keywords=samples['keywords'];cids=samples['cids']
    if args.mode=='upstream' and (len(set(keywords))<30 or len(set(cids))<30):parser.error('upstream mode requires 30 distinct keywords and CIDs; use a fresh service to avoid cached values')
    requests=[('categories','/api/es/categories')]
    count=1 if args.mode=='cold' else 10 if args.mode=='hot' else 30
    for i in range(count):
        kw=keywords[i%len(keywords)];cid=cids[i%len(cids)]
        requests.extend([('search','/api/es/search?'+urlencode({'q':kw,'page':1,'size':25})),('product','/api/es/product/'+cid)])
    values={};errors=0
    for label,path in requests:
        start=time.perf_counter()
        try:
            with urlopen(base+path,timeout=40) as response:response.read()
            values.setdefault(label,[]).append((time.perf_counter()-start)*1000)
        except Exception as exc:
            errors+=1;print(json.dumps({'route':label,'error':type(exc).__name__}))
    for label,items in values.items():
        ordered=sorted(items)
        print(json.dumps({'mode':args.mode,'route':label,'n':len(items),'p50_ms':round(statistics.median(items),2),'p95_ms':round(ordered[min(len(items)-1,int(len(items)*.95))],2),'errors':errors,'cacheExpectation':('upstream' if label=='search' else 'service-cache-after-first')}))


if __name__=='__main__':main()
