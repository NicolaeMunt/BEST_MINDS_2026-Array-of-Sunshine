# Logica pipeline-ului de imagini

Pentru fiecare decizie: ce am ales, ce am respins și de ce. Scris pentru cineva care nu a văzut codul.
Deciziile sunt în ordinea în care le-am luat. Fiecare se sprijină pe o măsurătoare pe date reale sau pe
un test cu răspuns cunoscut (o problemă plantată pe o copie a imaginii), iar scripturile `measure_*.py`
refac cifrele.

## Pe scurt

Pentru fiecare parcelă și fiecare scenă Sentinel-2:
1. luăm doar fereastra parcelei; scenele în care norii acoperă sigur peste jumătate din parcelă nu se
   descarcă deloc;
2. micșorăm parcela cu 20 m de la margine și aruncăm tot ce nu e sigur vegetație, sol gol sau apă,
   cu încă 20 m în jur; dacă rămâne sub 50% din parcelă, scena e sărită și listată separat;
3. un pixel e slab dacă NDVI-ul lui e cu peste 0,10 sub mediana parcelei; petele sub 0,1 ha se ignoră;
4. sectorul e direcția de la centrul parcelei spre zona cea mai mare, sau „împrăștiat” dacă nu există
   una dominantă;
5. ne comparăm cu scena acceptată anterioară relativ la mediana parcelei, deci maturarea, creșterea și
   diferențele dintre sateliți se anulează; scăderea întregii parcele se raportează separat;
6. NDMI (apa din frunze) e raportat doar ca context, fără etichetă de stres de apă;
7. overlay-ul și poza sunt reproiectate în proiecția hărții, ca să nu fie deplasate cu 30 m;
8. orice motiv de prudență apare în `warnings`, cu un cod fix.
9. totul rulează singur o dată pe zi pe server, iar rezultatele rămân în baza de date ca istoric, pe
   fiecare parcelă identificată prin numărul ei cadastral.
10. regulile depind de faza culturii, pe un calendar comun cu alertele senzorilor: un NDVI mic sau în
   scădere e avertisment doar cât cultura ar trebui să fie verde; via și livada au prag propriu și un
   filtru pentru iarba dintre rânduri.

## Cadrul pentru hackathon

Lucrăm pe o singură parcelă (`demo1`). Deciziile s-au luat pe trei date aproape fără nori (28.06, 30.06
și 18.07.2026) plus una înnorată pentru testul măștii (28.07). După ce a mers totul cap-coadă, am rulat
același cod pe tot sezonul, 1 mai – 31 iulie. Rezultatele se scriu doar pe disc (`out/`); trimiterea la
server (`push.py`) vine când există serverul.

## Sursa: Sentinel-2 L2A de pe Earth Search

Folosim reflectanța la sol (L2A) de pe Earth Search, fără cont. Zona Orhei este în tile-ul 35TPN, în
proiecția UTM 35N (EPSG:32635). Aducem poligonul parcelei în UTM, nu imaginea în lat/lon: reproiectarea
imaginii ar amesteca pixeli vecini și ar schimba valorile pe care le măsurăm.

## Corecția de +1000 (offset BOA) — verificată pe pixeli reali

**Ales:** scădem 1000 din valori doar dacă `earthsearch:boa_offset_applied` este fals. Toate scenele
noastre au valoarea adevărat, deci nu scădem nimic.
**Respins:** offset-ul `-0.1` scris în metadatele STAC ale fiecărei benzi.
**De ce:** am citit pixeli reali din 28.06. Pe vegetație, banda roșie are valori de ~190–550; dacă am
scădea 1000, reflectanța ar ieși negativă și NDVI median ar fi 1,48 (imposibil, maximul e 1). Fără
scădere, NDVI median e 0,71, normal pentru sfârșit de iunie. Metadatele se contrazic, iar datele arată
că offset-ul e deja scos.

## Citim doar fereastra parcelei, aliniată la grila de 20 m

**Ales:** pentru fiecare bandă descărcăm doar dreptunghiul parcelei plus 100 m margine, cu marginile
puse pe grila de 20 m a tile-ului.
**Respins:** descărcarea fișierelor întregi (~100–250 MB pe bandă); interpolarea benzilor de 20 m pe
grila de 10 m.
**De ce:** cu marginile pe grila de 20 m, fiecare pixel de 20 m acoperă exact 2×2 pixeli de 10 m, deci
îl copiem, fără să inventăm valori. Pentru harta de clase (SCL) asta e singura variantă corectă: o
clasă de nor nu se poate „media” cu una de vegetație. Marginea de 100 m există ca un nor aflat chiar
lângă parcelă să poată fi lărgit peste ea.

## Două scene în aceeași zi

**Ales:** dacă tile-ul are două scene în aceeași zi (de exemplu 30.06: S2A și S2B), o păstrăm pe cea
cu mai mulți pixeli utilizabili în fereastră; la egalitate, prima în ordine alfabetică.
**De ce:** e aceeași zi și același câmp, deci alegem scena care vede mai mult din el.

## Descărcarea și analiza sunt separate

**Ales:** `fetch.py` este singurul script care folosește rețeaua și scrie totul în `cache/`, care
intră în git. Analiza citește doar din `cache/`.
**De ce:** demo-ul merge fără internet, iar o a doua rulare nu mai descarcă nimic. Dacă descărcarea
automată nu merge, fișiere luate manual pot fi decupate în același format, iar analiza rămâne
neschimbată.

## Alegerea parcelei demo

Am descărcat o zonă de ~12×12 km în jurul Orheiului (`fetch.py --area`, nu intră în git) și am
comparat NDVI pe cele trei date. Între 28.06 și 18.07, solul gol din zonă se dublează (12% → 24%):
grâul și orzul se recoltează. De aceea parcela demo trebuie să fie o cultură care rămâne verde pe
toate datele; altfel orice regulă ar raporta o parcelă recoltată ca „100% afectată”.

Fiecare candidat a primit un contur desenat de mână în interiorul câmpului (`candidates.geojson`),
nu unul decupat după valorile NDVI: un contur făcut din NDVI ar lăsa afară exact pixelii slabi pe
care vrem să-i numărăm. Măsurătorile sunt în `measure_fields.py` și `out/selection/`.

## Parcela demo1: câmpul J4 (NE de Orhei)

**Ales:** câmpul J4, cu conturul desenat la 30 m în interiorul marginilor (47,5 ha; cel mai apropiat
pixel recoltat e la 22 m de contur). Cultura e trecută ca `"maize"`, **presupusă, nu confirmată**:
am dedus-o din calendar. Câmpul rămâne verde până la 18.07, când cerealele din jur sunt deja
recoltate, ceea ce se potrivește cu o cultură de vară (porumb sau floarea-soarelui). Nimeni n-a
verificat-o pe teren.
**Ce am măsurat:** doar 1,4% / 1,1% / 0,0% din pixeli sunt cu peste 0,10 sub mediana NDVI.
Variația (dungi diagonale, o pată mai slabă în centru-nord) e reală, pentru că se repetă aproape
identic la două zile distanță (corelație 0,97), dar e mică (~0,03 NDVI).
**Nu coborâm pragul ca J4 să pară afectată.** Dacă analiza arată o parcelă sănătoasă cu variație
minoră, acesta e rezultatul corect și îl arătăm așa. O parcelă cu o zonă slabă reală o caută
separat un coleg; poligonul ei trece prin același cod.

## Respinse: K10 și D3

**K10** avea 18% din pixeli sub mediană − 0,10, dar e o graniță între loturi, nu o zonă slabă.
Am recunoscut-o după două semne: (1) benzile din interior au margini drepte, orizontale, iar blocul
de sud e un dreptunghi curat; stresul culturii nu face linii drepte, hotarele dintre loturi da;
(2) diferența dintre nord și sud se micșorează în timp (0,134 → 0,110 → 0,085 NDVI): partea de
nord „recuperează”, cum face o cultură semănată mai târziu, nu o zonă stresată în plin iulie.
**D3** pe 18.07 are 25% sol gol: o pajiște cosită sau uscată. E exact falsul pozitiv pe care
vrem să-l evităm.
Criteriul „procent sub mediană” nu face diferența între o zonă slabă și un contur care prinde două
loturi; o fac doar imaginea și evoluția în timp.

## Indicele principal: NDVI

**Ales:** NDVI, la 10 m. **Respins:** EVI și NDRE.
**De ce:** am comparat cât de mult iese variația reală a câmpului peste zgomotul de la o zi la
alta (28 vs 30.06). Pe J4: NDVI 5,3×, EVI 5,5×, NDRE 3,9×. EVI vede același lucru ca NDVI, dar
are nevoie de banda albastră, mai sensibilă la ceață, și e mai greu de explicat. NDRE e la 20 m și
estompează dungile late de 10–30 m. NDVI nu se saturează pe J4 (95% din pixeli sunt sub 0,83).
Procentul „sub mediană − 0,10” nu se poate compara între indici, pentru că fiecare are altă scară.

## Sateliții nu dau aceeași valoare: comparăm relativ la mediana parcelei

**Măsurat:** între 28.06 (Sentinel-2C) și 30.06 (Sentinel-2A) nu se schimbă nimic real pe câmp în
două zile, totuși mediana NDVI scade cu 0,02–0,03 pe toate câmpurile măsurate (J4 0,785 → 0,754;
K10 0,830 → 0,809; D3 0,622 → 0,599). NDRE crește în aceleași zile cu 0,03–0,05.
**Consecință:** nu comparăm valori absolute de NDVI între scene. Fiecare pixel se compară cu
mediana parcelei din aceeași scenă, iar comparația între scene se face pe aceste abateri relative.
Altfel o diferență de calibrare între sateliți ar arăta ca o schimbare pe tot câmpul.

## Procentul de nori al scenei nu spune nimic despre parcelă

Am citit harta de clase (SCL) pentru toate scenele din mai–iulie, doar în fereastra parcelei.
Pe 15.07 scena are 18% nori, dar parcela e acoperită 100%; pe 18.06 scena are 22,5% nori, iar
parcela 0%. De aceea decidem pe pixelii din parcelă, nu pe procentul scenei.

## Data înnorată pentru testul măștii: 28.07.2026

**Ales:** scena Sentinel-2C din 28.07, care în interiorul parcelei are 35% nori, 32% umbră de nor
și 32% vegetație curată, adică toate cele trei situații pe aceeași parcelă. Intră în cache ca a
patra dată.
**De ce:** pe cele trei date curate masca nu are ce să arunce, deci n-am putea vedea dacă
funcționează.

## Masca de nori: păstrăm doar ce e sigur bun, lărgit cu 20 m

**Ales:** păstrăm doar pixelii pe care harta de clase (SCL) îi marchează vegetație, sol gol sau apă.
Orice altă clasă (nor, umbră de nor, cirus, „neclasificat”, „zonă întunecată”, fără date) se aruncă,
iar zona aruncată se lărgește cu 20 m (un pixel SCL) de jur împrejur.
**Respins:** varianta inversă (aruncăm doar ce e sigur rău) și lărgirile de 40–100 m.
**De ce:** pe 28.07, pixelii „neclasificați” apar exact la marginea norilor mici; varianta „doar ce e
sigur bun” îi aruncă și nu costă nimic în zilele senine (100% valid pe toate trei). Lărgirea de 40 m
n-a adus nimic măsurabil pe 28.07: pixelii de lângă nor nu erau mai întunecați decât cei mai
îndepărtați (−0,063 NDVI față de 18.07, atât la 0–10 m, cât și la 40–60 m de nor), dar ar fi
aruncat încă 7% din parcelă. 20 m acoperă imprecizia marginilor SCL, care e la rezoluție de 20 m.
Limita testului: pe 28.07 toți pixelii rămași sunt la sub 100 m de un nor, deci n-am avut cu ce
compara „departe de nori”. Norii care scapă de mască îi mai prindem o dată la comparația între scene.

## Micșorarea poligonului: 20 m, la toate parcelele

**Ales:** păstrăm doar pixelii al căror centru e la peste 20 m de marginea poligonului.
**Respins:** 10 m și 0 m.
**De ce:** am măsurat NDVI în funcție de distanța față de marginea câmpului, pe 18.07, când vecinii
sunt recoltați. La 10 m în interiorul câmpului pixelul e cu 0,03 sub nivelul câmpului, cât toată
variația naturală a J4, deci marginea ar apărea ca un fals inel slab. De la 20 m în interior
valorile sunt curate. Costul: demo1 păstrează 4188 din 4750 de pixeli. Un pătrat de 150×150 m ar
pierde aproape jumătate (225 → 121 de pixeli).
**Încredere scăzută:** dacă după micșorare rămân sub 200 de pixeli (~2 ha), rezultatul primește un
avertisment în `warnings`. Nu avem variantă de rezervă cu 10 m: aceeași regulă pentru toate parcelele.

## Pragul de pixeli valizi: 50% din parcelă

**Ales:** dacă după mască rămâne sub 50% din parcela micșorată, scena e sărită pentru acea parcelă
și nu produce niciun rezultat.
**Respins:** 30% și 70%.
**De ce:** referința noastră e mediana parcelei. Dacă se vede doar o bucată din câmp, mediana poate
veni chiar din zona slabă și o face să dispară, sau invers. La 50%, mediana vine din majoritatea
câmpului. La 70% am pierde scene utile din zilele parțial înnorate. 28.07 (24,6% valid) e sărită.

## Fișierul de ieșire: rezultate și scene sărite separat

`out/imagery.json` are două liste. `results` conține câte un obiect pe parcelă și scenă acceptată,
cu câmpurile anunțate echipei plus `warnings` (listă de texte, goală dacă totul e în regulă).
`skipped` conține scenele sărite, cu `parcel_id`, `scene_date`, `valid_pct` și `reason`; ele nu se
trimit la server ca rezultate, ca să nu apară pe hartă o scenă pe care n-o putem citi.

## Pixel slab: cu peste 0,10 sub mediana parcelei

**Ales:** un pixel e slab dacă NDVI-ul lui e cu peste 0,10 sub mediana NDVI a parcelei din aceeași
scenă (mediana pixelilor valizi, după mască și micșorare).
**Respins:** pragul fix 0,15 (ideea inițială), pragul relativ (15% sub mediană) și pragul statistic
MAD (de 3 ori împrăștierea obișnuită a câmpului, minimum 0,05).

**Dovada: testul cu pata plantată.** J4 e sănătos, deci pe el toate regulile dau aproape nimic
(0–1,3%) și nu le putem compara. Pe o copie a imaginii din 28.06 am scăzut artificial NDVI-ul
într-o pată din nord-est, cu mărime și intensitate cunoscute. Apoi am numărat cât din pată găsește
fiecare regulă și câți pixeli marchează în afara ei. E un test cu răspuns cunoscut, ca verificarea
unui detector de fum cu fum controlat. Pata există doar în `measure_threshold.py` și nu ajunge în
rezultate.

| Regula | pată pe 10%, −0,12 | 10%, −0,20 | 30%, −0,12 | 30%, −0,20 | marcat în afara petei |
|---|---|---|---|---|---|
| fix 0,15 | 44% | 100% | 18% | 95% | 0,0% |
| **fix 0,10** | **97%** | 100% | **71%** | 100% | 0,7–1,0% |
| relativ 15% | 81% | 100% | 55% | 100% | 0,4% |
| MAD 3 împrăștieri | 75% | 100% | 2% | 45% | 0–0,4% |

Pragul 0,15 vede doar problemele grave; o problemă moderată (−0,12) trece aproape neobservată.
Pragul 0,10 le prinde și pe cele moderate, cu un cost de ~1% pixeli răzleți pe un câmp sănătos
(0,6% după curățare). Pe J4, 0,10 înseamnă cam de 3 ori împrăștierea naturală a câmpului (0,035),
deci un câmp sănătos ajunge rar acolo.

**De ce a fost respins MAD:** pragul MAD se calculează din împrăștierea câmpului, iar o problemă
mare mărește chiar această împrăștiere. Cu o pată pe 30% din câmp, împrăștierea crește de la 0,035 la
0,067, pragul coboară de la 0,68 la 0,57 și problema nu mai iese sub el: doar 2% găsit la o problemă
moderată și 45% la una gravă. Regula ratează exact problemele mari, adică pe cele care contează cel
mai mult.

**Limitele pragului ales:**
1. **Subestimează petele mari.** Referința e mediana parcelei, iar când o parte mare din câmp e
   slabă, mediana coboară odată cu ea (de la 0,783 la 0,768 cu o pată pe 30%). La o problemă moderată
   pe 30% din câmp găsim 71%, nu 97%. Dacă peste jumătate din câmp e slab, problema devine mediana și
   nu mai apare deloc. Cazul ăsta trebuie prins de comparația cu scena anterioară.
2. **E validat doar la NDVI ~0,75** (J4, sfârșit de iunie–iulie). La început de sezon (NDVI ~0,3–0,5)
   pixelii amestecă plantele cu solul dintre ele, iar 0,10 poate însemna altceva. Pentru acea
   perioadă nu avem măsurători.

## Curățarea zgomotului: ignorăm zonele sub 10 pixeli

**Ales:** pixelii slabi care se ating, inclusiv pe diagonală, formează o zonă. Zonele mai mici de
10 pixeli (1.000 m², adică 0,1 ha) se ignoră. `affected_pct` e procentul de pixeli valizi rămași în
zone slabe **după** curățare.
**Respins:** fără curățare; „deschiderea” morfologică 3×3 (erodare, apoi creștere la loc).
**De ce:** pe J4 (28.06) pixelii slabi scad de la 1,3% la 0,9%. Rămân două zone reale în nord, care
apar și pe 30.06, și dispar punctele răzlețe (zgomot, un stâlp). Pe pata plantată curățarea nu atinge
problema (97% găsit înainte și după) și scade marcările din afara ei de la 1,0% la 0,6%. Deschiderea
3×3 ar fi coborât J4 la 0,2%, dar șterge și dungile reale mai înguste de 30 m și roade marginile
fiecărei zone.

**Rezultat pe demo1:** 0,9% / 0,9% / 0,0% afectat (28.06 / 30.06 / 18.07), cu două zone mici în
nord, adică o parcelă sănătoasă cu variație minoră.

## Unde e zona: direcția de la centrul parcelei spre centrul zonei celei mai mari

**Ales:** `affected_sector` e direcția de la centrul parcelei spre centrul zonei slabe celei mai
mari, rotunjită la una din 8 direcții (`N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW`). Dacă centrul
zonei e în treimea interioară a razei parcelei (raza unui cerc cu aceeași suprafață; pentru demo1
~365 m, deci ~120 m), sectorul e `C` (centru). Dacă zona cea mai mare ține sub 50% din suprafața
slabă, nu există o direcție dominantă și sectorul e `scattered`. Fără zone slabe, sectorul e `null`.
**Respins:** caroiajul 3×3 pe dreptunghiul din jurul parcelei și centrul tuturor pixelilor slabi.
**De ce:** am plantat pete în locuri cunoscute (`measure_sector.py`). J4 stă pe diagonală, așa că
colțurile caroiajului 3×3 sunt aproape goale, iar o pată din nord-est ieșea „N” la orice metodă de
alegere. Direcția de la centru a numit-o corect „NE”. Centrul tuturor pixelilor slabi cade în gol când
zonele sunt pe părți opuse sau împrăștiate: la două pete (NE și SV) și la patru pete mici spunea
„centru”, unde nu era nimic. Zona cea mai mare cu pragul de 50% spune „NE” la două pete (zona mare
ține 65%) și „împrăștiat” la patru pete egale (cea mai mare ține 21%).

**Câmpuri noi, de anunțat echipei:**
- `zone_count`: numărul de zone slabe rămase după curățare, ca propoziția să poată spune
  „în nord-est (+2 zone mai mici)”.
- `zone_center`: `[lon, lat]` al centrului zonei celei mai mari, în aceleași coordonate ca
  poligonul, pentru un marcaj pe hartă. E `null` când `affected_pct` e 0 sau sectorul e `scattered`.
  Am verificat că pe demo1 cade pe un pixel slab din parcelă.

**Limită: sectorul poate sări între date când zonele sunt apropiate ca mărime.** Pe J4 sunt două zone
mici în nord, de 24 și 13 pixeli, care își schimbă locul la mărime între 28.06 și 30.06. „Cea mai mare”
e deci alta, iar sectorul trece din `NW` în `N`, deși pe câmp nu s-a schimbat nimic. Ambele răspunsuri
spun „în nord”, deci e acceptabil, dar cine citește rezultatele în timp trebuie să știe că o schimbare
de sector între două direcții vecine nu înseamnă că problema s-a mutat.

## Overlay-ul și poza: reproiectate în proiecția hărții, mărite prin copierea pixelilor

**Motivul reproiecției: un decalaj de 27–33 m.** Analiza lucrează pe grila UTM, care la Orhei e
rotită cu 1,37° față de nordul geografic. Harta web (Leaflet) întinde un PNG între patru margini
lat/lon, cu nordul în sus. Dacă am pune imaginea UTM direct între margini, colțurile ar fi deplasate
cu 27–33 m, adică zonele ar apărea pe hartă la ~3 pixeli alături, mai mult decât micșorarea de 20 m.
De aceea doar imaginile de afișare (nu analiza) sunt reproiectate în Web Mercator, proiecția hărții,
iar `overlay_bounds` sunt marginile exacte ale acestei grile, în ordinea [S, V, N, E].
Leaflet le cere ca `[[S, V], [N, E]]`.

**Mărirea fără pixeli neclari:** la reproiecție fiecare pixel de 10 m devine un pătrat de 8×8 pixeli
de 1,25 m, prin copiere, nu prin netezire. Dacă am trimite PNG-ul la 10 m, browserul l-ar mări
neted și marginile zonelor ar deveni neclare. Mărirea vine gratis odată cu reproiecția, care oricum
e obligatorie. Respins: zonele ca poligoane vectoriale, pentru că ar fi schimbat contractul
(`overlay_path` n-ar mai fi PNG) și ar fi cerut muncă în frontend.

**Ce arată overlay-ul:** doar zonele slabe, cu roșu 67% opac, ca textura câmpului să se vadă
dedesubt, plus un contur alb subțire (2,5 m) în jurul fiecărei zone, ca zonele mici să se vadă și să
nu depindem doar de roșu pe verde. Partea parcelei ascunsă de nori într-o scenă acceptată e gri 43%
opac („aici nu se vede”). Restul e transparent. Pentru o scenă fără zone slabe overlay-ul e
transparent, ca frontendul să nu aibă caz special.
**Respins:** harta continuă a abaterii de la mediană (pe J4, cu doar 0,9% afectat, făcea câmpul să
pară plin de probleme și contrazicea propoziția) și zonele doar conturate (umplerea slabă se pierdea).

**Poza:** imaginea color ESA (TCI), reproiectată pe aceeași grilă și cu aceleași colțuri ca
overlay-ul, deci dreptunghiul parcelei plus 40 m în jur, ca să se vadă și vecinii. E luminată o
singură dată, cu aceeași formulă pentru toate datele, pentru că originalul e prea întunecat; o
luminare calculată pe fiecare imagine ar fi făcut pozele de la date diferite necomparabile.

**Verificare:** `check_map.py` așază poza și overlay-ul exact cum face Leaflet, folosind doar PNG-ul
și `overlay_bounds`. Desenează deasupra poligonul parcelei și `zone_center` și verifică automat că
`zone_center` cade pe un pixel roșu. Pe demo1 conturul stă pe câmp, iar marcajul e pe zonă la
ambele date cu zone.

## Comparația cu scena anterioară: relativă la mediana parcelei

**Ales:** fiecare scenă acceptată se compară cu scena acceptată anterioară a aceleiași parcele (cele
sărite nu contează), doar pe pixelii valizi în ambele. Un pixel s-a înrăutățit dacă NDVI-ul lui a
scăzut cu peste 0,10 **mai mult decât mediana parcelei**, adică distanța lui sub mediană a crescut cu
0,10. Zonele înrăutățite sub 10 pixeli se ignoră, ca la pasul 3. `declined_pct` e procentul de
pixeli înrăutățiți din pixelii comparați.
**Respins:** comparația absolută (prima idee: „a scăzut cu peste 0,10”) și „slab nou” (slab acum,
nu era slab înainte).
**De ce:** pe perechea 28.06 → 30.06 (2 zile, nimic real schimbat) am plantat schimbări pe a doua
scenă (`measure_change.py`):

| Situație | Schimbarea medianei | absolută | **relativă** | „slab nou” |
|---|---|---|---|---|
| real 28.06 → 30.06 | −0,032 | 0% | 0% | 0,3% |
| real 30.06 → 18.07 | −0,007 | 0% | 0% | 0% |
| zonă nouă în NE (−0,20) | −0,033 | găsește 100% | găsește 100% | găsește 97% |
| maturare uniformă (−0,15) | −0,182 | 100% din câmp | 0% | 0,3% |
| maturare + zonă nouă | −0,183 | 100% peste tot | 100% din zonă, 0% în afară | 97% |
| creștere uniformă (+0,08) | +0,048 | 0% | 0% | 0,3% |

Comparația absolută marchează tot câmpul la maturare, iar o zonă nouă reală se pierde în roșul de
peste tot. „Slab nou” face zone noi false (0,3% pe perechea reală de 2 zile), pentru că pixelii de la
limita pragului sar înăuntru și afară de la o zi la alta, și nu vede o zonă deja slabă care se
agravează. Comparația relativă anulează orice schimbare uniformă: maturare, creștere și diferența de
0,02–0,03 dintre sateliți.

## Schimbarea pe toată parcela se raportează separat

**Ales:** `median_change` (mediana de acum minus mediana scenei anterioare) apare la fiecare rezultat.
Dacă scade cu peste 0,10, rezultatul primește avertismentul „toată parcela a scăzut”.
**De ce:** comparația relativă și pragul de la pasul 3 se raportează la mediană, deci nu văd o
problemă care cuprinde peste jumătate din câmp, pentru că mediana coboară odată cu ea. Schimbarea
medianei o vede. Pragul de 0,10 e de peste 3 ori diferența dintre sateliți (0,03). Din imagine nu
putem spune dacă e maturare, recoltare sau secetă; aici ajută senzorii de sol și calendarul culturii.

**Câmpuri noi, de anunțat echipei:** `prev_scene_date` (data scenei anterioare), `median_change` și
`declined_pct`. Pentru prima scenă a unei parcele toate trei sunt `null`. Zonele înrăutățite nu
apar deocamdată în overlay.

**Scena anterioară prea veche:** dacă scena anterioară e la peste 30 de zile, rezultatul primește un
avertisment. Comparația se face, dar spune puțin, pentru că în o lună câmpul se schimbă mult și din
motive normale.

## Nori scăpați de mască, la comparație: avertisment „posibil nor”

**Ales:** dacă o zonă înrăutățită are un pixel la mai puțin de 100 m de pixeli aruncați de masca de
nori în aceeași scenă, rezultatul primește un avertisment: „posibil un nor pe care masca l-a ratat”.
**De ce:** un nor subțire nevăzut de SCL ar arăta exact ca o zonă înrăutățită, iar norii scăpați
stau de obicei la marginea celor detectați.
**Verificat pe un caz plantat**, cu funcția din pipeline. Pe o copie a scenei din 30.06 am marcat ca
mascat un „nor” rotund de ~70 m rază, o zonă înrăutățită cu marginea la 40 m de el și o alta la
328 m. Avertismentul a numărat exact o zonă, pe cea de lângă nor. Norul fără zonă și zona fără nor
n-au dat avertisment. Tot cu cazuri plantate am verificat avertismentul „toată parcela a scăzut”
(maturare de −0,15 → mediana −0,18) și pe cel de vechime (40 de zile).
**Limită:** prinde doar norii scăpați de lângă norii detectați. Un nor pe care SCL nu l-a văzut
deloc, într-o scenă altfel senină, trece neobservat. Pe datele demo avertismentul nu se declanșează,
pentru că toate scenele acceptate sunt 100% senine.
**Pentru produsul real:** o zonă înrăutățită ar trebui considerată sigură doar dacă se vede și la
următoarea trecere a satelitului (2–5 zile). Asta prinde orice efect trecător (nor, umbră, sol ud
după ploaie), cu prețul unei alerte întârziate. N-am făcut-o acum: cere ținut minte starea între
scene și ar complica rezultatele în ultimele ore.

## NDMI: doar la nivel de parcelă, fără etichetă de stres de apă

**Ales:** raportăm `ndmi_median` (NDMI-ul tipic al parcelei) și `ndmi_change` (față de scena
anterioară; `null` la prima scenă). NDMI = (B8A − B11) / (B8A + B11), la 20 m, și arată apa din
frunze, nu umiditatea solului. Din imagine nu punem nicio etichetă de „stres de apă”: pe aceasta o
dau senzorii de sol, iar NDMI e context („apa din frunze e stabilă sau scade”).
**Ce am măsurat pe J4** (`measure_ndmi.py`): NDMI e stabil (se repetă la 2 zile distanță cu
corelație 0,99, zgomot 0,006) și aproape nu simte diferența dintre sateliți (−0,003, față de −0,032 la
NDVI). În interiorul câmpului NDMI urmează NDVI aproape perfect: **corelație 0,98, pantă ~1,4**, adică
NDMI coboară de 1,4 ori cât NDVI. Harta NDMI e practic o copie mai neclară a hărții NDVI.
**Respins: eticheta „NDMI mai mic în zonă”.** În cele 4 zone slabe reale NDMI e cu 0,14–0,15 sub
mediană, dar exact cât prezice NDVI-ul lor mai mic (0,15–0,18). Zonele au NDMI mic doar pentru că
acolo vegetația e mai rară. Eticheta ar fi pus „stres de apă” pe toate zonele, adică o concluzie falsă.
**Respins acum: eticheta „mai uscat decât explică NDVI”** (NDMI-ul zonei comparat cu cât prezice
NDVI-ul ei). Pe J4 n-ar marca nimic, ceea ce e corect: zonele sunt chiar puțin mai umede decât ar
prezice NDVI (+0,01 până la +0,03). Dar n-avem niciun câmp cu stres real ca să calibrăm pragul și să
arătăm că funcționează. Un test plantat ar verifica doar aritmetica, nu agronomia. În plus, zonele
mici au doar 6–11 pixeli distincți de 20 m.
**Direcții pentru produsul real:**
1. Eticheta „mai uscat decât explică NDVI”, calibrată pe câmpuri cu stres de apă confirmat.
2. Semnalul „NDMI scade, NDVI stabil” pe toată parcela. Frunzele pierd apă înainte să se vadă în
   verdeață, deci ar fi un indiciu timpuriu de uscare. Pe J4 nu apare: între 30.06 și 18.07 NDMI a
   crescut cu 0,05, cu NDVI stabil.

## Tot sezonul (mai–iulie): nu descărcăm benzile scenelor care sigur vor fi sărite

**Ales:** pentru fiecare scenă din interval, `fetch.py` citește întâi doar harta de clase (SCL), care e
mică. Calculează cât din parcela micșorată are o clasă păstrată de mască (vegetație, sol gol, apă),
înainte de lărgirea cu 20 m. Lărgirea doar scoate pixeli, deci `valid_pct` din analiză nu poate
depăși această valoare. Dacă ea e sub 50%, analiza ar sări oricum scena, așa că celelalte benzi nu
se mai descarcă. Scena rămâne în cache doar cu SCL și apare în `skipped`, cu `valid_pct` calculat din
SCL cu aceeași mască, lărgire și micșorare.
**De ce:** citim puțin de pe rețea fără să pierdem nimic. Regula nu poate arunca o scenă pe care
analiza ar fi acceptat-o. Tot această valoare, calculată pe parcelă (nu pe toată fereastra), alege
între două scene din aceeași zi.

**Rezultat pe demo1, 1 mai – 31 iulie 2026:** 46 de date cu scene ale tile-ului 35TPN, citite în 155 de
secunde, cu ~274 MB de pe rețea. 23 de scene acceptate și 23 sărite. Pentru 21 dintre cele sărite n-am
descărcat decât harta de clase, pentru că parcela era acoperită de nori. Cache-ul parcelei are 2,6 MB.
Graficul sezonului e în `out/demo1/season.png` (`season_chart.py`, care citește doar `imagery.json`).

**Ce arată sezonul** (observații, nu decizii):
- **Mai:** sol gol, apoi răsărire (NDVI 0,14 → 0,35, NDMI negativ). Nicio zonă slabă, ceea ce e corect,
  dar „0% afectat” pe un câmp unde încă nu crește nimic poate fi citit greșit ca „totul e bine”.
- **31.05–10.06, creștere rapidă** (NDVI 0,40 → 0,64, +0,11 până la +0,12 pe scenă): zone împrăștiate pe
  1,4–3,6% din parcelă, probabil răsărire neuniformă sau sol vizibil printre rânduri. Aici pragul de
  0,10 nu e validat; l-am validat doar la NDVI ~0,75.
- **18.06–03.07, platou** (NDVI 0,75–0,80): zona din nord-vest apare în 4 scene la rând (18, 20, 25,
  28.06), iar pata din centru-nord pe 28.06–03.07. O zonă care se repetă la mai multe treceri e
  aproape sigur reală; e exact ideea „confirmării la următoarea trecere” propusă pentru produsul real.
- **20.07:** e vizibilă doar jumătatea de sud (51,5% valid). NDVI scade cu 0,062, iar NDMI crește cu
  0,063, adică în sens opus. Pare voal de nor rămas după mască, dar scăderea e uniformă, deci nicio
  regulă nu se declanșează. E o limită: o scenă abia peste pragul de 50% poate avea mediana luată
  dintr-o parte nereprezentativă a câmpului.
- **30.07:** NDVI 0,647, NDMI 0,222 (−0,13 față de 20.07, dar 20.07 e suspectă). Față de 18.07 scad
  amândouă (NDVI −0,10, NDMI −0,06), deci nu e semnalul „NDMI scade, NDVI stabil”.

## Început de sezon: avertisment sub NDVI 0,6

**Ales:** dacă mediana NDVI a parcelei e sub 0,6, rezultatul primește avertismentul `low_vegetation`:
vegetația nu acoperă încă solul, iar zonele slabe pot fi răsărire neuniformă sau sol gol.
**Respins:** doar o notă (fermierul ar citi „0% afectat” pe un câmp gol ca „totul e bine”) și
ascunderea cifrelor (`affected_pct` `null`) sub 0,3. Avertismentul păstrează cifrele și explică ce
înseamnă.
**De ce 0,6:** regula de pixel slab e validată la NDVI ~0,75. Sub 0,6 se vede solul printre rânduri.
Pe demo1 avertismentul apare pe cele 11 scene din 1.05–5.06 (NDVI 0,14–0,52) și dispare de la 10.06
(0,64).

## Avertismentele au cod fix

**Ales:** fiecare element din `warnings` e `{"code": ..., "text": ...}`. Scorul de prioritate citește
doar codul, iar textul e pentru oameni. Codurile sunt:

| Cod | Când apare |
|---|---|
| `low_pixel_count` | sub 200 de pixeli în parcelă după micșorarea de 20 m |
| `low_vegetation` | mediana NDVI sub 0,6 (început de sezon) |
| `possible_cloud` | o zonă slabă sau înrăutățită la sub 100 m de pixeli aruncați de masca de nori |
| `whole_field_drop` | mediana NDVI a scăzut cu peste 0,10 față de scena anterioară |
| `stale_previous` | scena anterioară e la peste 30 de zile |

**De ce:** dacă scorul ar căuta cuvinte în propoziții, orice reformulare a textului l-ar strica.

## „Posibil nor” se aplică și zonelor slabe

**Ales:** avertismentul `possible_cloud` verifică, cu aceeași regulă de 100 m, și zonele slabe ale
scenei, nu doar zonele înrăutățite față de scena anterioară.
**De ce:** pe 10.06 două zone slabe stăteau lipite de un nor mascat și nu primeau niciun avertisment,
pentru că nu erau „înrăutățite” (câmpul creștea uniform). Pe tot sezonul avertismentul apare pe 10.06
(cele 2 zone de lângă nor), pe 20.06 (zona din nord-vest, care e reală și se repetă în alte 3 scene,
deci acolo e doar o prudență în plus) și pe 30.07 (zona din colțul de nord-vest, văzută o singură
dată). Avertismentul nu șterge nimic, doar cere prudență.

## Zona confirmată de scena anterioară

**Ales:** `zone_confirmed` e `true` când zona principală (cea care dă sectorul) se suprapune cu pixeli
slabi ai scenei acceptate anterioare, și `false` altfel. E `null` la prima scenă a parcelei, când nu
există zone slabe sau când zonele sunt împrăștiate.
**Verificat pe date reale:** zona din nord-vest iese `true` pe 20, 25 și 28 iunie, iar zona din 30.07
iese `false`, cum era de așteptat. Tot `true` ies 10.06 (NE), 30.06 și 03.07 (N), confirmate fiecare de
scena dinainte.
**Atenție la sens:** `false` înseamnă **neconfirmată**, nu „infirmată”. Zona din 30.07 era în partea
acoperită de nori pe 20.07 (0 din 25 de pixeli vizibili), deci scena anterioară n-a văzut locul.
Pentru produsul real, comparația ar trebui făcută cu ultima scenă care a văzut acel loc.

## Corecție: marcajul zonei stă întotdeauna pe zonă

La rularea pe tot sezonul, verificarea hărții (`check_map.py`) a găsit un caz în care `zone_center` nu
cădea pe roșu: pe 10.06 zona principală e o fâșie curbată, iar centrul ei geometric cade în afara ei,
pe un pixel sănătos. Am corectat: `zone_center` e acum pixelul zonei cel mai apropiat de centrul ei
geometric. La zonele compacte marcajul se mută cu ~3 m, spre centrul celui mai apropiat pixel. La
zonele curbate ajunge pe zonă. Sectorul se calculează în continuare din centrul geometric, ca înainte,
și nu s-a schimbat pe nicio dată. După corecție, toate cele 7 marcaje din sezon cad pe roșu.

## Limite cunoscute, adunate

- Pragul de 0,10 e validat doar la NDVI ~0,75; la început de sezon apare avertismentul `low_vegetation`.
- Petele mari sunt subestimate, pentru că mediana coboară odată cu ele; o problemă pe peste jumătate
  din câmp se vede doar prin `median_change` și avertismentul `whole_field_drop`.
- Sectorul poate sări între direcții vecine când două zone au mărimi apropiate.
- `possible_cloud` prinde doar norii scăpați de lângă cei detectați; un nor nevăzut deloc de SCL trece.
- O scenă abia peste 50% valid poate avea mediana luată dintr-o parte nereprezentativă a câmpului
  (20.07 pe demo1).
- Cultura e presupusă (porumb), nu confirmată; NDMI nu spune nimic despre sol.
- Pe demo1 nu există o problemă reală mare: e o parcelă sănătoasă cu variație minoră, iar acesta e
  rezultatul pe care îl arătăm.

## Identificatorii parcelelor: numărul cadastral

**Ales:** fiecare parcelă e identificată prin **numărul ei cadastral**: 10 cifre, codul zonei cadastrale
plus numărul terenului, scris de obicei cu punct după a 7-a cifră (`6401307.101`). În demo numerele sunt
**fictive** și marcate ca atare (`ids_fictive`), ca să nu arătăm proprietatea unor oameni reali.
`demo1`, cum apare mai sus în acest fișier, e J4, adică `6401307.101`. Aceleași numere le folosesc și
senzorii (`sensors-alerts`), deci senzorii și satelitul vorbesc despre același câmp.
**Respins:** `P1`–`P5`, care nu spun nimic, și „conturul SIPA”. În Moldova, SIPA e **Sistemul Informațional
al Piețelor Agricole** (piață, prețuri). Sistemul pentru parcele și subvenții e **LPIS**, încă în
dezvoltare și fără un format public de identificator; câmpul `lpis_parcel` rămâne gol până atunci.
**Limită:** un lan cultivat nu e mereu un singur teren cadastral, pentru că pământul e fragmentat în
fâșii (vezi K10). Pentru un produs real, cheia ar trebui să fie parcela LPIS, cu o listă de numere
cadastrale atașată.

## J4 e probabil floarea-soarelui, nu porumb

Am adăugat pentru zona de 12 km încă 7 date senine (16.05 – 3.10). În zonă, câmpurile de vară se împart
în două grupuri, la ~3 săptămâni distanță:

| Data | J4 | grupul timpuriu | grupul târziu |
|---|---|---|---|
| 5 iunie | 0,52 | 0,52 | 0,37 |
| 28 iunie | **0,78** (vârf) | **0,80** (vârf) | 0,71 |
| 18 iulie | 0,74 | 0,77 | **0,81** (vârf) |
| 22 august | **0,29** (uscat) | 0,36 | **0,59** (verde) |

J4 se comportă identic cu grupul timpuriu, adică floarea-soarelui (vârf la sfârșit de iunie, uscată în
august, recoltată la început de septembrie). Grupul târziu e porumbul.
**Argument împotrivă:** în pozele color din iulie J4 nu arată galbenul înfloririi. Nu e decisiv, pentru că
de sus și la 10 m florile nu se văd mereu. Cultura rămâne **presupusă** (`crop_confirmed: false`), dar
acum din curba sezonului, nu din calendar.

## Cele cinci parcele

Fiecare dintre cele 5 culturi din `sensors-alerts` are o parcelă. Am ales câmpuri al căror comportament
pe satelit se potrivește cu cultura; altfel juriul ar vedea o „livadă” recoltată în iulie.
**Metoda:** pe zona de 12 km am clasificat fiecare pixel după curba lui pe sezon:
- grâu: verde la 5.06, recoltat la 18.07;
- floarea-soarelui: verde la 28.06, uscată la 22.08;
- porumb: verde la 22.08, gol la 3.10;
- verde tot sezonul: livezi, vii, păduri.

Am găsit câmpurile întregi din fiecare clasă și le-am ordonat după mărime și distanța până la J4. Livada
și via le-am confirmat după textură (rânduri), pentru că NDVI singur nu le deosebește de pădure.
**Respinși:** un „candidat de livadă” de 28,7 ha era un sat cu grădini (case vizibile), cercul verde de
lângă J4 e pădure, iar un „candidat de vie” era râpa cu iarbă de la est de J4.

| Număr cadastral (fictiv) | Nume | Cultură | Unde | Curba NDVI pe sezon |
|---|---|---|---|---|
| `6401307.101` | Lotul de Floarea-soarelui | floarea-soarelui | J4, NE de Orhei | vârf 0,78 la 28.06 → 0,29 la 22.08 |
| `6401307.102` | Câmpul Mare | grâu | lipit de J4, la NV | 0,77 în mai–iunie → 0,24 la 18.07 |
| `6401204.045` | Via Nord | viță-de-vie | ~4,7 km N | 0,46–0,69 tot sezonul |
| `6401512.033` | Lanul de Porumb | porumb | ~5 km S | vârf 0,87–0,89 iunie–august, 0,63 la 22.08 |
| `6401512.058` | Livada Sud | livadă | ~6 km S | 0,66–0,85 tot sezonul |

**Două corecturi după analiza pe tot sezonul:**
- **Grâul:** primul contur prindea **două loturi**. O linie dreaptă tăia triunghiul, iar toate „zonele
  slabe” (până la 27%) stăteau doar deasupra ei: e lecția de la K10. Am păstrat doar lotul de jos
  (~12,7 ha), iar „zonele slabe” au dispărut.
- **Livada:** marginea de est era prea aproape de iarba vecină, așa că apărea o fâșie dreaptă „slabă” de
  1–2 pixeli de-a lungul marginii. Am retras marginea cu 50 m, iar fâșia a dispărut.

În ambele cazuri semnul a fost același: **o „zonă slabă” cu margine dreaptă e aproape mereu un hotar,
nu o problemă a culturii.**

## Descărcarea pentru mai multe parcele

**Ales:** o singură căutare în catalog pentru toate parcelele, apoi descărcarea dată cu dată, cu toate
parcelele odată, ținând în memorie (cache GDAL, 512 MB) bucățile de fișier deja aduse.
**De ce:** parcelele vecine stau în aceleași bucăți de 10 km ale imaginii. Măsurat: prima parcelă dintr-o
zi durează 6–9 s, iar următoarele 0–2 s. Tot sezonul (1 mai – 3 octombrie) pentru 5 parcele s-a descărcat
în ~9 minute, iar cache-ul are ~13 MB.

## Rularea zilnică pe server

**Ales:** un fir de execuție din API, ca firul care colectează senzorii. El pornește jobul de satelit:
- în fiecare seară la 21:00 (Sentinel-2 trece peste Moldova pe la prânz, iar scena apare în catalog
  după câteva ore);
- la pornirea API-ului, dacă ultima rulare bună e mai veche de o zi;
- la `POST /imagery/refresh`.

Jobul (`fetch.py`, apoi `analyze.py`) rulează ca **proces separat**, cu Python-ul lui (`imagery/.venv`).
API-ul exportă înainte parcelele din bază, iar după rulare citește `out/imagery.json` și îl salvează.
**Respins:** jobul în interiorul procesului API, pentru că ar fi adus în backend dependențe grele (GDAL),
minute de descărcare în procesul care servește pagina și riscul ca o eroare GDAL să dărâme API-ul. Am
respins și un cron separat de API, care ar fi cerut ca serverul să fie pornit pentru primire și două
locuri de configurat.

**Baza de date:**
- tabelele noi sunt în aceeași bază ca senzorii: `users`, `parcels`, `imagery_results`,
  `imagery_warnings`, `imagery_skipped` și `imagery_runs`;
- imaginile rămân fișiere, iar baza păstrează doar calea;
- importul e idempotent: pentru fiecare (parcelă, dată) primită șterge ce exista, ca rezultat sau ca scenă
  sărită, apoi scrie din nou;
- fiecare rând păstrează `rules_version`, amprenta codului de analiză, ca să se știe cu ce reguli a fost
  calculat.

**Verificat:**
- **o rulare pornită din API** (cu o bază de test) a pus în bază 390 de perechi (parcelă, dată) în ~1 minut;
- **pentru 15 iulie** API-ul dă poza din 5 iulie („de acum 10 zile”), plus cele 5 scene sărite din cauza
  norilor între 7 și 15 iulie;
- **același fișier importat a doua oară** n-a adăugat nimic;
- **următoarea rulare** e programată corect la 21:00.

## Ce a arătat sezonul complet: de rezolvat cu regulile pe culturi

- **Via:** mediana NDVI a unei vii stă sub 0,6 toată vara, deci `low_vegetation` apare în 38 din 44 de
  scene. Pragul de 0,6 e pentru culturi de câmp, nu pentru vie.
- **Livada:** în iulie–august apar zone „slabe” de 10–13% care formează o rețea între blocurile de pomi.
  E iarba dintre rânduri, care se usucă vara, nu pomii. Livezile și viile au nevoie de o regulă proprie,
  de exemplu la o scară mai mare decât rândurile.
- **Floarea-soarelui:** uscarea din august e treptată, iar fiecare pas e sub 0,10, deci `whole_field_drop`
  nu apare. E corect după definiție (avertismentul e pentru căderi bruște), dar o uscare mai devreme
  decât normal pentru cultură s-ar putea semnala doar cu o curbă așteptată pe cultură.
- **Grâul, 5 iunie:** o zonă slabă la marginea unui nor e marcată corect cu `possible_cloud`.
- **Porumbul:** sănătos tot sezonul, cel mult 2,3% slab.

Rezolvate în secțiunea următoare: avertismentele urmează faza culturii, via și livada au prag propriu,
iar livada și via au filtrul de formă pentru rânduri.

## Reguli pe culturi: totul depinde de faza culturii

**Ideea.** Pericolul depinde de faza în care e cultura, nu doar de cultură: −1 °C e grav pentru grâul în
înflorire și nu contează pentru grâul strâns. Regulile vechi aveau un singur prag pe tot sezonul. Ele dădeau
alerte când nu mai era nimic de stricat (înghețul din 29 septembrie la toate cele 5 parcele) și erau prea
blânde exact în fazele sensibile.

**Calendarul fazelor (ales: calendar fix pe cultură).** Fiecare cultură are fazele ei, cu data de
început pentru zona Orhei, în `sensors-alerts/src/main/resources/application.yml`. Același fișier e citit
de serviciul de senzori (Java), de API (bilanțul apei, istoricul) și de pipeline-ul de satelit, deci
pragurile nu se pot dezalinia.

Am respins două variante:
- grade-zile din temperatura senzorului: cer data semănatului;
- faza ghicită din curba satelitului: merge doar pentru culturile de câmp.

Prețul: într-un an timpuriu sau târziu, calendarul poate greși cu 1–2 săptămâni.

Datele vin din surse și din ce a văzut satelitul în 2026:
- grâul se coace de la ~20 iunie (la noi: 25 iunie) și se strânge în iulie (FAO GIEWS);
- floarea-soarelui înflorește în iulie și se usucă de la ~20 iulie;
- porumbul se usucă de la ~15 august (la noi: 16 august) și se strânge din octombrie (FAO);
- via dezmugurește în a treia decadă a lui aprilie și înflorește în prima decadă a lui iunie (Institutul
  Național de Viticultură și Vinificație);
- mărul înflorește în masă pe 25 aprilie – 10 mai (agroexpert.md).

**Înghețul pe faze.** Pragurile critice sunt temperaturile la care începe paguba, din surse:

| Cultură | Faza | Prag critic | Sursa |
|---|---|---|---|
| Grâu | alungire / burduf / spicuire–înflorire / formarea boabelor | −4 / −2 / −1 / −2 °C, câte 2 ore | Kansas State, C646 |
| Porumb | până la 5 frunze, punctul de creștere e sub pământ | −2 °C câteva ore (la 0 °C mor doar frunzele) | Purdue |
| Porumb | după maturitatea fiziologică (de la ~20 septembrie) | înghețul nu mai scade recolta | Purdue |
| Floarea-soarelui | cotiledoane – 4 frunze / buton–înflorire / umplerea semințelor | −3 / −1 / −4 °C | Manitoba, NDSU/SDSU |
| Măr | dezmugurire / buton / înflorire și fructe tinere / fructe în coacere | −5 / −2,8 / −2 / −2 °C | Iowa State după WSU (10% flori moarte, 30 min); Penn State pentru fructe |
| Vie | lăstari tineri / struguri în coacere | −1 / −2 °C | WSU, Penn State |

Avertizarea vine de obicei cu 2 °C înainte de pragul critic. În nopțile calme mugurii sunt mai reci decât
aerul, deci e nevoie de timp pentru pornit protecția. În fazele fără prag (repaus, nesemănat, după
recoltare), înghețul nu dă alertă.

Pe istoricul inventat de dinainte, efectul ar fi fost:
- dispăreau alertele din 29 septembrie la grâu, floarea-soarelui și porumb;
- porumbul tânăr primea 4 nopți CRITICAL la 0…−1,6 °C, temperaturi pe care le suportă; rămânea doar
  noaptea de −3 °C.

Sfatul de îngheț poate fi și pe fază. Merele în coacere și strugurii primesc alt sfat decât florile.

**Riscul de boală: ore de aer umed, nu o citire.** O singură citire umedă nu înseamnă boală: ciupercile au
nevoie de frunze ude câteva ore, la o anumită temperatură, într-o anumită fază. Senzorul nu măsoară
frunza udă, așa că folosim umiditatea aerului de cel puțin 90% (95% la vie) ca aproximare. Regula: cel
puțin N ore umede din ultimele W, la temperatura bolii, doar în fereastra ei.

| Cultură | Boala | Condiția | Când | Sursa |
|---|---|---|---|---|
| Grâu | fuzarioza spicului | 48 din ultimele 168 de ore, 15–30 °C | 20 mai – 15 iunie | modelele de risc FHB (De Wolf și alții) |
| Porumb | helmintosporioză | 6 ore la rând, 18–27 °C | 15 iunie – 31 august | Univ. Minnesota, Crop Protection Network |
| Floarea-soarelui | putregai alb pe calatidiu | 48 din ultimele 72 de ore, sub 29 °C | 1–25 iulie (înflorire) | NDSU, SDSU |
| Livadă | rapăn | 6 ore la 16–24 °C, 12 ore de la 9 °C, 15 ore de la 7 °C, 28 de ore de la 4 °C | 1 aprilie – 31 mai | tabelul Mills revizuit, Penn State |
| Vie | mană | 4 ore la rând cu cel puțin 95%, 13–29 °C | 15 mai – 31 august | APS, NSW DPI |

Prima variantă închidea riscul imediat ce condiția nu mai era îndeplinită. Pe date reale, la porumb pe
24 iunie, alerta a venit la 02:00, iar „riscul a trecut” la 04:00, deși umiditatea era 99%: doar
temperatura coborâse sub 18 °C. De aceea **riscul rămâne 24 de ore după ultima oră în care condiția a fost
îndeplinită**. Așa, o perioadă ploioasă dă o singură alertă, iar fermierul are timp să trateze.

**Aerul fierbinte și uscat.** Regula veche alerta la umiditate scăzută, la orice temperatură. Acum alerta
pornește la umiditate ≤ 30% **și** temperatură ≥ 25 °C. Aceasta e definiția suhoveiului din glosarul
serviciului meteo al Moldovei (meteo.md). Vântul de peste 5 m/s din definiție nu îl măsurăm.

Alerta e activă doar în fazele în care strică:
- grâul: până la recoltare;
- porumbul: înflorire și umplerea boabelor;
- floarea-soarelui: iulie – mijlocul lui august;
- livada și via: iunie–august.

Și această alertă ține 24 de ore. Senzorul vede aerul, nu solul, deci mesajul spune „aer fierbinte și
uscat”, nu „sol uscat”.

**Când trebuie udat: bilanțul apei din sol (FAO-56).** În fiecare zi cultura consumă Kc × ET0, iar ploaia
dă apă înapoi:
- ET0 vine din temperatura minimă și maximă a zilei (Hargreaves, FAO-56 ecuația 52), deci ajunge
  senzorul nostru.
- Kc e coeficientul fazei (FAO-56, tabelul 12).
- Solul ține 170 mm de apă pe metru de rădăcini (FAO-56, tabelul 19, lut prăfos).
- Adâncimea rădăcinilor e mijlocul intervalului din FAO-56, tabelul 22.
- Cultura suferă când lipsesc peste p × apa totală (p din același tabel). Atunci vine „E timpul să udați”.
- Pornim pe 1 mai cu solul plin, după ploile de primăvară.
- Nu știm dacă fermierul a udat, deci presupunem un câmp neirigat.

Prima încercare a folosit adâncimea minimă a rădăcinilor (1 m la porumb). Satelitul a arătat că era greșit:
modelul spunea că porumbul a rămas fără apă pe 24 iulie, dar NDVI-ul lui a stat la 0,86 până la jumătatea
lui august. Cu mijlocul intervalului FAO, modelul și satelitul se potrivesc:

| Cultură | De udat din | Sol aproape gol din | Ce a văzut satelitul |
|---|---|---|---|
| Floarea-soarelui | 6 iulie | 2 august | NDVI scade de la sfârșitul lui iulie; 0,54 pe 4 august |
| Porumb | 16 iulie | 3 august | NDVI scade de la 16 august |
| Livadă | 30 iunie | 24 iulie | iarba dintre rânduri se usucă din iulie |
| Vie | 18 iulie | – | – |
| Grâu | – (strâns înainte) | – | – |

Cantitatea afișată e cât trebuie ca să iasă cultura din stres: deficitul minus pragul. Să umpli tot solul
ar cere de 2 ori mai mult, iar „udați 255 mm” nu e un sfat realist.

**Istoricul și demo-ul, pe vreme reală.** Sezonul exemplu era inventat și avea vârfuri de umiditate de o
singură oră, deci regulile de boală n-ar fi dat nimic pe el. Acum e vremea reală din 2026 la fiecare
parcelă, de la Open-Meteo (reanaliză ERA5, CC BY 4.0, aceeași sursă ca noaptea de îngheț), și se
potrivește zi cu zi cu satelitul. Nu e o măsurătoare din câmp, iar ERA5 netezește minimele nopții.

Pe 2026, regulile dau 70 de alerte în loc de 230:
- risc de fuzarioză la grâu: 8–14 iunie, după săptămâna ploioasă 1–7 iunie;
- rapăn la livadă: de 3 ori în mai;
- mană la vie: de 8 ori;
- helmintosporioză la porumb: de 4 ori;
- aer fierbinte și uscat: 1–23 august;
- risc de îngheț la livadă și vie: 1 și 3 mai.

Butoanele de demo „zile umede” și „zile de arșiță” redau accelerat prima perioadă reală din 2026 cu alertă
pentru cultura parcelei. Unde n-a existat o asemenea perioadă, demo-ul spune cinstit că nu are ce reda:
- floarea-soarelui n-a avut nicio perioadă umedă în înflorire, pentru că iulie a fost secetos;
- grâul n-a avut nicio zi de arșiță înainte de recoltare.

Noaptea reală de îngheț e acum 8–9 aprilie 2025: −3,2 °C la livadă, când mărul era în buton (prag
−2,8 °C). Noaptea din 1 aprilie 2020 cădea înainte de fazele sensibile ale culturilor noastre.

**Pe satelit:**
- `low_vegetation` și `whole_field_drop` sunt avertismente doar cât cultura ar trebui să fie verde
  (sezonul `growing` din calendar). Înainte de răsărire și după coacere, un NDVI mic sau în scădere e
  normal. API-ul arată faza la fiecare scenă (`phase`, `season`).
- Pragul `low_vegetation` e pe cultură: vie 0,4, livadă 0,5, câmp 0,6. Pixelul de 10 m amestecă rândul cu
  iarba dintre rânduri (OENO One), iar via noastră a stat între 0,44 și 0,69 tot sezonul.
- La livadă și vie, zonele slabe mai înguste de 3 pixeli (30 m) se elimină înainte de curățarea zonelor
  mici. Acelea sunt alei și benzi de iarbă; petele compacte de pomi bolnavi rămân. Filtrul nu se aplică la
  culturile de câmp, unde ar șterge zonele mici reale (la floarea-soarelui, 28 iunie: 0,9% → 0).

Ce s-a schimbat pe 2026:
- `low_vegetation`: de la 122 la 0. Toate cădeau în faze în care un NDVI mic e normal; în fazele de
  creștere, nicio cultură n-a coborât sub prag.
- `whole_field_drop`: de la 2 la 0. Ambele erau maturare normală (grâul pe 25 iunie, porumbul pe 22
  august).
- Rețeaua de iarbă din livadă: de la 5–13,5% la 0, în 13 din 14 scene. Pe 28 iulie rămâne o pată de 8,8%
  lângă un nor, deja marcată `possible_cloud`.
- Toate cele 18 marcaje de zonă rămase cad pe roșu.

## Senzorul de sol: temperatura la 5 cm și umiditatea la 20 cm

**De ce.** Senzorul de aer nu vede udarea: apa ajunge direct în sol, iar bilanțul calculat presupunea mereu
un câmp neudat. Acum fiecare stație are și o sondă de sol, care măsoară:
- temperatura solului la ~5 cm, adâncimea semințelor;
- umiditatea solului la ~20 cm, ca procent de apă din volumul solului.

Datele sezonului vin tot din Open-Meteo (ERA5-Land, straturile 0–7 cm și 7–28 cm), de la 1 aprilie, ca să se
vadă și semănatul.

**Udarea după senzor.** Pragul vine din aceleași valori FAO-56 ca bilanțul (lut prăfos: capacitate de câmp
27%, punct de ofilire 10%): cultura suferă sub capacitatea de câmp − p × (capacitatea de câmp − punctul de
ofilire). Asta înseamnă 17,6% la porumb și grâu, 18,5% la livadă și 19,4% la floarea-soarelui și vie.

Am ales pragurile FAO, nu o calibrare pe fiecare parcelă: e mai simplu, și senzorul spune același lucru ca
bilanțul. Pe 2026, cele două au dat date apropiate pentru „de udat”:

| Cultură | Senzor | Bilanț |
|---|---|---|
| Floarea-soarelui | 1 iulie | 6 iulie |
| Livadă | 7 iulie | 30 iunie |
| Porumb | 11 iulie | 16 iulie |

Când senzorul a raportat în ultimele două zile, decizia e a lui; altfel rămâne bilanțul.

**Udarea văzută de senzor.** Umiditatea crește cu cel puțin 3 puncte în 6 ore și n-a plouat (sub 2 mm) în
ultimele 48 de ore. Prima variantă căuta ploaie doar în ultimele 6 ore și a găsit „udări” false în mai și
iunie: ploaia ajunge la 20 cm cu întârziere. Cu 48 de ore nu mai apare nicio udare falsă pe tot sezonul.

Două corecturi au venit din teste:
- Alerta pornea și se oprea când umiditatea stătea chiar la prag. Acum iese din „de udat” abia la 2 puncte
  peste prag.
- În ultimele 6 ore aplicația folosește ultima citire din fiecare minut, nu media orei. Altfel o udare făcută
  în aceeași oră cu uscarea se pierdea în medie.

**„Poți semăna”.** Porumbul și floarea-soarelui răsar uniform când solul de la adâncimea semințelor stă la
cel puțin 10 °C (Purdue, Iowa State, NDSU). Regula: media zilei ≥ 10 °C la 5 cm, trei zile la rând, în
aprilie–mai. Cele trei zile sunt alegerea noastră pentru „constant”, pentru că sursele nu dau un număr. În
2026, la Orhei, regula a dat 5 aprilie. Spre deosebire de calendarul fix, ea urmează solul parcelei, deci
merge și în nordul, și în sudul Moldovei.

**Demo.** Butonul „S-a udat” ridică umiditatea solului la capacitatea de câmp în 30 de secunde, fără ploaie.
Testat pe livadă:
1. După „zile de arșiță”, solul rămâne la 17,2%, așa că aplicația trimite „E timpul să udați”.
2. După „S-a udat”, solul urcă la 27%, iar aplicația trimite singură „S-a udat”.

## Data semănatului mută calendarul culturii

Calendarul fix e potrivit pentru zona Orhei și pentru un an obișnuit. Fermierul poate da acum, pe profil, data
la care a semănat fiecare teren. La porumb și floarea-soarelui, calendarul presupune o zi de semănat (20, respectiv
10 aprilie). Dacă terenul a fost semănat cu N zile mai târziu, toate fazele lui se mută cu N zile, la fel
ferestrele de boală și de arșiță. Asta schimbă pragurile de îngheț, sfatul de udare și ce e normal pe satelit.

Exemplu, porumbul semănat pe 10 mai:
- pe 25 septembrie e încă în „coacere”, cu prag de îngheț de −2 °C; după calendarul fix ar fi deja la
  „maturitate”, când înghețul nu mai contează;
- scena din 3 septembrie e la „înflorire și umplerea boabelor”, deci o scădere a verdelui ar fi avertisment,
  nu maturare normală.

Am respins varianta în care grâul de toamnă primește aceeași mutare: dezvoltarea lui de primăvară ține de
vremea din primăvară, nu de ziua semănatului din toamnă. La grâu, data doar se păstrează și se afișează.

O dată mai departe de 60 de zile de calendar e luată drept greșeală de scriere și ignorată.

Odată ce terenul e semănat, sfatul „poți semăna” nu mai apare. Mutarea e implementată la fel în trei
locuri: serviciul de senzori (`CropCalendar.forSowing`), backend (`crops.for_sowing`) și pipeline-ul de
satelit (`common.phase_on`).
