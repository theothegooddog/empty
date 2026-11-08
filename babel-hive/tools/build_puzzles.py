import wordfreq, unicodedata, re, collections, json, random, sys
LANGS='en es fr de it pt nl sv nb da pl cs tr ro ca hu'.split()
from spylls.hunspell import Dictionary
HS={L:Dictionary.from_files(f'dicts/{L}/package/index') for L in LANGS}
TH=3.4
SPECIAL={'ß':'ss','æ':'ae','ø':'o','ł':'l','đ':'d','ı':'i','œ':'oe','þ':'th','ð':'d'}
BLOCK=set('''fuck fucking fucked fucker shit shitty cunt cock dick dicks pussy bitch bitches slut whore twat wank wanker penis vagina anal anus rape raped rapist nigga nigger niggas fagot faggot porn porno sexy horny boobs tits titty dildo cum cumming jizz
puta putas puto putos mierda coño cono joder follar polla verga pinche chingar chinga cabron cabrona pendejo pendeja culo culos maricon marica zorra
merde putain pute salope connard connasse conne enculer encule bite couille couilles nique niquer foutre bordel chier
scheisse scheiß scheisse fotze ficken fick wichser arsch arschloch hure schwanz titten nutte
cazzo cazzi fottere fottuto stronzo stronza troia puttana vaffanculo figa minchia culo coglione coglioni merda
caralho porra foda foder fodase buceta piroca viado puta merda cuzao bosta
kut lul neuken kanker hoer klootzak godverdomme tering
fitta kuk knulla jävla javla hora fan faen helvete kuken pikk fanden knep knepp
vittu perkele paska kyrpa huora
kurwa kurwy chuj huj pierdolic jebac jebany pizda dupa
kurva prdel kokot pica hovno
amk orospu sik sikis siktir got piç yarrak amina
pula pizda futu muie
coli puta merda collons
anjing bangsat kontol memek ngentot
kurva fasz picsa geci baszd baszni
'''.split())
def norm(w):
    w=''.join(SPECIAL.get(c,c) for c in w.lower())
    return ''.join(c for c in unicodedata.normalize('NFKD',w) if not unicodedata.combining(c))
BLOCKN={norm(b) for b in BLOCK}
words={}   # norm -> {lang: display}
for L in LANGS:
    for w in wordfreq.iter_wordlist(L):
        z=wordfreq.zipf_frequency(w,L)
        if z<TH: break
        n=norm(w)
        if not re.fullmatch('[a-z]{4,}',n) or len(set(n))>7 or 's' in n: continue
        if n in BLOCKN or any(b in n for b in BLOCKN if len(b)>=5): continue
        if L!='en':
            ze=wordfreq.zipf_frequency(w,'en')
            if ze>=3.0 and z<ze-0.3: continue   # English loanword noise
        h=HS[L]
        try:
            ok=h.lookup(w) or (L=='de' and h.lookup(w.capitalize()))
        except Exception: ok=False
        if not ok: continue
        d=words.setdefault(n,{})
        if L not in d: d[L]=w
def mask(w):
    m=0
    for c in w: m|=1<<(ord(c)-97)
    return m
bymask=collections.defaultdict(list)
for w in words: bymask[mask(w)].append(w)
pang=[m for m in bymask if bin(m).count('1')==7]
print('words',len(words),'pangram sets',len(pang),file=sys.stderr)
def subsets(m):
    s=m
    while s:
        yield s; s=(s-1)&m
puzzles=[]
for m in pang:
    sub=[(s,bymask[s]) for s in subsets(m) if s in bymask]
    for i in range(26):
        if not m>>i&1: continue
        c=1<<i
        ans=[w for s,ws in sub if s&c for w in ws]
        if 25<=len(ans)<=75:
            pg=[w for w in ans if mask(w)==m]
            # require a pangram that is reasonably common in some language
            good=[w for w in pg if max(wordfreq.zipf_frequency(words[w][l],l) for l in words[w])>=3.6]
            langs={l for w in ans for l in words[w]}
            vow=sum(1 for v in 'aeiou' if m>>(ord(v)-97)&1)
            lc=collections.Counter(l for w in ans for l in words[w]); top=lc.most_common(1)[0][1]
            if good and top<=0.45*len(ans) and len(langs)>=9 and 2<=vow<=4 and 'en' in langs: puzzles.append((m,i,sorted(ans)))
print('puzzles',len(puzzles),file=sys.stderr)
random.seed(7)
random.shuffle(puzzles)
seen=set(); chosen=[]
for m,i,ans in puzzles:
    if m in seen: continue
    seen.add(m); chosen.append((m,i,ans))
    if len(chosen)>=500: break
used=sorted({w for _,_,a in chosen for w in a})
idx={w:k for k,w in enumerate(used)}
dic=[]
for w in used:
    e=words[w]
    # compact: "word|lang:display,lang:display" (display omitted if same as word)
    parts=[l if e[l]==w else l+':'+e[l] for l in LANGS if l in e]
    dic.append(w+'|'+','.join(parts))
out={'langs':LANGS,'dict':dic,'puzzles':[]}
for m,i,ans in chosen:
    letters=''.join(chr(97+k) for k in range(26) if m>>k&1)
    out['puzzles'].append([chr(97+i),letters.replace(chr(97+i),''),[idx[w] for w in ans]])
json.dump(out,open('data.json','w'),ensure_ascii=False,separators=(',',':'))
print('chosen',len(chosen),'dict',len(dic),file=sys.stderr)
