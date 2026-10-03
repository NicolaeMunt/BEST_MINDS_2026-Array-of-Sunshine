# Logica pipeline-ului de imagini

Pentru fiecare decizie: ce am ales, ce am respins și de ce. Scris pentru cineva care nu a văzut codul.

## Cadrul pentru hackathon

Lucrăm pe o singură parcelă (`demo1`) și pe trei date aproape fără nori: 28.06, 30.06 și 18.07.2026.
Rezultatele se scriu doar pe disc (`out/`); trimiterea la server (`push.py`) vine mai târziu, când există
serverul. Restul scenelor din mai–iulie le adăugăm după ce merge totul cap-coadă.

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
