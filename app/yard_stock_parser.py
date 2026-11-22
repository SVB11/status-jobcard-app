"""Allow-list-only stock sheet extraction. Original uploads are never retained.
PDF: Microsoft Print To PDF table geometry; ambiguous/unknown layouts fail closed.
Only the eight permitted fields leave this module; discarded columns never enter a row.
"""
import io
import re
import zipfile
from collections import Counter

SECTIONS = ('TANKERS', 'TRUCK TRACTORS', 'RIGIDS', 'TRAILERS')
FIELDS = ('stock_number', 'section', 'year', 'make', 'model', 'description', 'registrations', 'availability')
STOCK = re.compile(r'^(?:CWS|SPWS|WS)\s*\d*[A-Z]*(?:-[A-Z0-9]+)?$', re.I)
START = re.compile(r'^((?:CWS|SPWS|WS)\s*\d+[A-Z]*(?:-[A-Z0-9]+)?|SPWS)(?:\s+|$)', re.I)
LIMIT = 500

class StockParseError(ValueError):
    pass

def clean(v, limit=300):
    s = re.sub(r'[\x00-\x1f\x7f]', ' ', str(v or '')).strip()
    return re.sub(r'\s+', ' ', s)[:limit]

def stock_key(value):
    """Exact identity: prefixes and suffixes retained, spaces/case normalised only."""
    return re.sub(r'\s+', '', clean(value, 40)).upper()

def match_key(value):
    """Conservative sale/photo matching; never strip arbitrary suffixes or prefixes."""
    s = stock_key(value)
    if re.fullmatch(r'\d{3,8}', s):
        s = 'WS' + s
    m = re.fullmatch(r'(WS\d+)(?:SL|RL|-S3P\d+)?', s)
    if m:
        return m.group(1)
    return s if re.fullmatch(r'(?:CWS|SPWS)\d+', s) else None

def validate_row(row):
    out = {k: clean(row.get(k), 600 if k == 'description' else 120) for k in FIELDS}
    out['stock_number'] = stock_key(out['stock_number'])
    issues = []
    if not STOCK.fullmatch(out['stock_number']) or not out['stock_number']:
        issues.append('Stock number needs correction')
    if not match_key(out['stock_number']):
        issues.append('Unnumbered or unfamiliar stock suffix; no automatic delivery match')
    if out['section'] not in SECTIONS:
        issues.append('Choose a section')
    if not re.fullmatch(r'(?:19|20)\d{2}', out['year']):
        issues.append('Year is not a confirmed four-digit year')
    if not out['make'] or not out['description']:
        issues.append('Make or description missing')
    if not out['availability'] or out['availability'].upper() not in ('AVAILABLE', 'APPROVAL'):
        issues.append('Availability needs review')
    regs = [r.strip() for r in out['registrations'].split('/') if r.strip()]
    if not regs or any(len(re.sub(r'[^A-Z0-9]', '', r.upper())) < 4 for r in regs):
        issues.append('Registration missing or placeholder')
    if len(out['stock_number']) > 32:
        issues.append('Stock number too long')
    return out, issues

def finish(rows, warnings):
    if not rows:
        raise StockParseError('No stock rows found. Use the master stock sheet layout.')
    if len(rows) > LIMIT:
        raise StockParseError('Maximum 500 stock rows per upload.')
    counts = Counter(stock_key(r['stock_number']) for r in rows)
    keys = Counter(match_key(r['stock_number']) for r in rows if match_key(r['stock_number']))
    result = []
    for r in rows:
        out, issues = validate_row(r)
        if counts[out['stock_number']] > 1:
            issues.append('Duplicate stock number: exclude or correct before confirming')
        if match_key(out['stock_number']) and keys[match_key(out['stock_number'])] > 1:
            issues.append('Shared base number: automatic delivery/photo matching disabled')
        result.append({'data': out, 'issues': issues, 'include': True})
    return {'rows': result, 'warnings': warnings, 'counts': dict(Counter(r['section'] for r in rows))}

def parse_pdf(raw):
    from pypdf import PdfReader
    try:
        doc = PdfReader(io.BytesIO(raw), strict=False)
        if doc.is_encrypted or len(doc.pages) > 12:
            raise StockParseError('Use an unencrypted stock PDF of 12 pages or fewer.')
        rows, warnings, section = [], [], None
        for page_no, page in enumerate(doc.pages, 1):
            bits = []
            def visit(t, cm, tm, font, size):
                if t.strip():
                    bits.append((float(tm[4]), float(tm[5]), clean(t, 2000)))
            page.extract_text(visitor_text=visit)
            # Layout mode measures real glyph widths. A fragment that runs on across a
            # column gap is cut at its first 2+ space gap so extras/mileage/price text
            # merged into one PDF string never reaches an imported field.
            runs = set()
            for line in page.extract_text(extraction_mode='layout', layout_mode_space_vertically=False).split('\n'):
                for run in re.split(r'\s{2,}', line):
                    run = clean(run, 2000)
                    if run:
                        runs.add(run)
            def first_run(text):
                best = None
                for run in runs:
                    if text == run or (text.startswith(run) and text[len(run):len(run)+1] == ' '):
                        if best is None or len(run) > len(best):
                            best = run
                return best or text
            # The master export uses a stable 1100-unit virtual page. Reject other layouts
            # rather than guess at price/CRM text. Header is often one text fragment.
            headers = [b for b in bits if 'WS/STOCK #' in b[2]]
            if not headers and page_no == 1:
                raise StockParseError('Stock table header not found; use the master PDF or XLSX.')
            regs = [b for b in bits if b[2].startswith('REG #')]
            if headers and (not regs or not all(780 < b[0] < 860 for b in regs)):
                raise StockParseError('Unrecognised PDF column layout. Use XLSX or the master Print To PDF layout.')
            anchors = sorted([b for b in bits if b[0] < 115 and START.match(b[2])], key=lambda b: b[1])
            sections = sorted([b for b in bits if b[0] < 115 and b[2] in SECTIONS], key=lambda b: b[1])
            for x,y,t in bits:
                if x < 115 and '#CALC!' in t:
                    warnings.append({'page': page_no, 'issue': 'Spreadsheet #CALC! line has no vehicle; excluded'})
            for idx, (x,y,t) in enumerate(anchors):
                prev_y = anchors[idx-1][1] if idx else -1000
                next_y = anchors[idx+1][1] if idx+1 < len(anchors) else 10000
                local_sec = [b[2] for b in sections if b[1] < y]
                sec = local_sec[-1] if local_sec else section
                if sec not in SECTIONS:
                    raise StockParseError('Stock row has no recognised section.')
                m = START.match(t); number = m.group(1)
                # Regs on double-reg trailer rows sit 6.5 units above/below the centre.
                # Midpoint ownership preserves both registrations without borrowing neighbours.
                lo = max(y-8, (prev_y+y)/2)
                hi = min(y+8, (next_y+y)/2)
                vals = {k: [] for k in FIELDS}
                vals['stock_number'] = [number]; vals['section'] = [sec]
                rest = t[m.end():].strip()
                if rest:
                    a = rest.split(' ', 1); vals['year'].append(a[0])
                    if len(a)>1: vals['make'].append(first_run(a[1]))
                for bx,by,bt in sorted(bits, key=lambda b:(b[1],b[0])):
                    if not lo <= by <= hi or (bx,by,bt)==(x,y,t):
                        continue
                    # Explicit column allowlist; EXTRAS (>=520), mileage and price never copied.
                    col = None
                    if 115 <= bx < 160: col='year'
                    elif 160 <= bx < 260: col='make'
                    elif 260 <= bx < 345: col='model'
                    elif 345 <= bx < 520: col='description'
                    elif 795 <= bx < 880: col='registrations'
                    elif 880 <= bx < 945: col='availability'
                    if col: vals[col].append(first_run(bt))
                row = {k: (' / ' if k=='registrations' else ' ').join(dict.fromkeys(v)) for k,v in vals.items()}
                rows.append(row)
            if sections: section=sections[-1][2]
        return finish(rows, warnings)
    except StockParseError:
        raise
    except Exception:
        raise StockParseError('Could not read stock PDF; try the master XLSX.') from None

ALIASES = {'WS/STOCK #':'stock_number','WS / STOCK #':'stock_number','STOCK #':'stock_number',
           'YEAR':'year','MAKE':'make','MODEL':'model','DESCRIPTION':'description',
           'REG #':'registrations','REG#':'registrations','REGISTRATION':'registrations',
           'AVAILABILITY':'availability'}

def parse_xlsx(raw):
    from openpyxl import load_workbook
    try:
        z=zipfile.ZipFile(io.BytesIO(raw))
        if sum(i.file_size for i in z.infolist()) > 30*1024*1024 or len(z.infolist())>2000:
            raise StockParseError('Workbook expands beyond the size limit.')
        if any('vbaProject' in n or 'externalLinks/' in n for n in z.namelist()):
            raise StockParseError('Macros and external workbook links are not accepted.')
        wb=load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
        rows, warnings=[],[]
        for sheet in wb:
            mapping, section, previous = {}, None, None
            for rn, cells in enumerate(sheet.iter_rows(),1):
                if rn>3000: raise StockParseError('Workbook exceeds 3000 rows per sheet.')
                if len(cells)>100: raise StockParseError('Workbook exceeds 100 columns.')
                texts=[clean(c.value) for c in cells]
                found=[v.upper() for v in texts if v.upper() in SECTIONS]
                if found: section=found[0]; previous=None; continue
                header={i:ALIASES[v.upper()] for i,v in enumerate(texts) if v.upper() in ALIASES}
                if 'stock_number' in header.values():
                    if not {'stock_number','make','description','registrations','availability'} <= set(header.values()):
                        raise StockParseError('Required stock headers missing.')
                    mapping=header; continue
                if not mapping: continue
                # Never inspect unapproved columns (including formulas/CRM) beyond header detection.
                row={k:'' for k in FIELDS}; row['section']=section or ''
                formula=False
                for i,k in mapping.items():
                    if i<len(cells):
                        if cells[i].data_type=='f': formula=True; row[k]=''
                        else: row[k]=texts[i]
                if not any(row[k] for k in FIELDS if k!='section') and not formula: continue
                if '#CALC!' in row['stock_number'] or formula:
                    warnings.append({'row':rn,'issue':'Formula/error in permitted column: excluded; paste values and re-upload'}); previous=None; continue
                if not row['stock_number'] and row['registrations'] and previous and not any(row[k] for k in ('year','make','model','description','availability')):
                    previous['registrations']+=' / '+row['registrations']; continue
                if not row['stock_number']:
                    warnings.append({'row':rn,'issue':'Unassigned line in stock columns: excluded for review'}); continue
                rows.append(row); previous=row
        wb.close()
        return finish(rows,warnings)
    except StockParseError: raise
    except Exception:
        raise StockParseError('Could not read workbook. Use XLSX, no macros; paste formulas as values.') from None
