from __future__ import annotations

import json, re, shutil, zipfile
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

OUT=Path('reports'); DBG=Path('debug'); OUT.mkdir(exist_ok=True); DBG.mkdir(exist_ok=True)
H={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36','Accept-Language':'ko-KR,ko;q=0.9'}
s=requests.Session(); s.headers.update(H)
manifest=[]

def save_resp(r,name):
    (DBG/name).write_bytes(r.content)
    return r

def verify_pdf(data): return data[:5]==b'%PDF-' and len(data)>10000

def download(url,name,referer=None):
    h={'Referer':referer} if referer else {}
    r=s.get(url,headers=h,timeout=60,allow_redirects=True); save_resp(r,name+'.raw')
    if verify_pdf(r.content):
        p=OUT/name; p.write_bytes(r.content); manifest.append({'file':name,'url':url,'size':len(r.content)}); return p
    return None

# 1) Chungbuk Techno Park
cbtp_page='https://www.cbtp.or.kr/index.php?board_id=board_106080502&control=bbs&mode=view&no=16&lm_uid=366'
r=s.get(cbtp_page,timeout=60); save_resp(r,'cbtp_page.html')
urls=[]
for a in BeautifulSoup(r.text,'html.parser').find_all('a',href=True):
    href=urljoin(cbtp_page,a['href'])
    if 'action=down' in href or '.pdf' in href.lower(): urls.append(href)
# known CP949 URL fallback
urls += ['https://www.cbtp.or.kr/index.php?action=down&board_id=board_106080502&control=util&dtype=up&fenc=r&file=2025%B0%A8%BB%E7%BA%B8%B0%ED%BC%AD_%C3%E6%BA%CFTP.pdf&no=16&task=down&where=dat']
for u in dict.fromkeys(urls):
    if download(u,'01_충북테크노파크_2025_감사보고서.pdf',cbtp_page): break

# 2) National Heritage Promotion Agency via ALIO
alio='https://www.alio.go.kr'
payload={'apbaType':[],'jidtDptm':[],'area':[],'apbaId':'C0191','reportFormRootNo':'32301','quart':''}
r=s.post(alio+'/item/itemOrganListJung.json',json=payload,timeout=60); save_resp(r,'alio_list.json')
try: data=r.json()['data']['organList']
except Exception: data=[]
for row in data:
    files=row.get('files') or ''
    for part in files.split('|'):
        if '@' not in part: continue
        fno,fname=part.split('@',1)
        if not fno: continue
        u=f"{alio}/download/file.json?f={fno}&d={row.get('disclosureNo','')}&s={row.get('submissionNo','')}"
        ext='.zip' if fname.lower().endswith('.zip') else '.pdf'
        rr=s.get(u,timeout=60); save_resp(rr,'alio_'+fno+'.raw')
        if verify_pdf(rr.content):
            p=OUT/'02_국가유산진흥원_최신_감사보고서.pdf'; p.write_bytes(rr.content); manifest.append({'file':p.name,'url':u,'size':len(rr.content),'source_name':fname}); break
        if rr.content[:2]==b'PK':
            z=OUT/'alio.zip'; z.write_bytes(rr.content)
            with zipfile.ZipFile(z) as zz:
                for n in zz.namelist():
                    b=zz.read(n)
                    if verify_pdf(b):
                        p=OUT/'02_국가유산진흥원_최신_감사보고서.pdf'; p.write_bytes(b); manifest.append({'file':p.name,'url':u,'size':len(b),'source_name':n}); break
            z.unlink(missing_ok=True)
    if (OUT/'02_국가유산진흥원_최신_감사보고서.pdf').exists(): break

# 3) ETRI / NST ONEST - crawl list and any download links, then Selenium fallback
etri='https://onest.re.kr/mgp/open/lst/moveMngmPblntList.do?pstinstCode=ETRI'
r=s.get(etri,timeout=60); save_resp(r,'etri_page.html')
links=[]
for a in BeautifulSoup(r.text,'html.parser').find_all('a',href=True):
    txt=(a.get_text(' ',strip=True)+' '+a['href']).lower()
    if '감사' in txt or 'audit' in txt or '.pdf' in txt: links.append(urljoin(etri,a['href']))
for m in re.findall(r"['\"]([^'\"]+(?:down|download|file)[^'\"]+)['\"]",r.text,re.I): links.append(urljoin(etri,m))
for u in dict.fromkeys(links):
    try:
        if download(u,'03_한국전자통신연구원_ETRI_최신_회계감사보고서.pdf',etri): break
    except Exception: pass

if not (OUT/'03_한국전자통신연구원_ETRI_최신_회계감사보고서.pdf').exists():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        o=Options(); o.add_argument('--headless'); o.add_argument('--no-sandbox'); o.add_argument('--disable-dev-shm-usage'); o.add_experimental_option('prefs',{'download.default_directory':str(OUT.resolve()),'download.prompt_for_download':False,'plugins.always_open_pdf_externally':True})
        d=webdriver.Chrome(options=o); d.get(etri)
        for el in d.find_elements(By.XPATH,"//*[contains(text(),'회계감사보고서') or contains(text(),'감사보고서')]"):
            try: el.click()
            except Exception: pass
        for a in d.find_elements(By.TAG_NAME,'a'):
            try:
                u=a.get_attribute('href') or ''; t=(a.text or '')
                if '.pdf' in u.lower() or '다운로드' in t or '첨부' in t:
                    if download(u,'03_한국전자통신연구원_ETRI_최신_회계감사보고서.pdf',etri): break
            except Exception: pass
        (DBG/'etri_selenium.html').write_text(d.page_source,encoding='utf-8'); d.quit()
    except Exception as e: (DBG/'selenium_error.txt').write_text(repr(e),encoding='utf-8')

(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
with zipfile.ZipFile('audit_reports.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in OUT.iterdir(): z.write(p,p.name)
print(json.dumps(manifest,ensure_ascii=False,indent=2))
