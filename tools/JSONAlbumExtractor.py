import sys, csv, json
from collections import OrderedDict

if len(sys.argv) == 2:
    input = './../albums/' + sys.argv[1] + '/' + sys.argv[1] + '.csv'
    output = './../albums/' + sys.argv[1] + '/' + sys.argv[1] + '.json'
elif len(sys.argv) == 3:
    input = sys.argv[1]
    output = sys.argv[2]
else:
    print("Insufficient arguments")
    sys.exit()

json_data = []
json_album = OrderedDict()
json_songs = []

currentAlbum = None

def addSong(line):
    multiArtist = False
    multiLyricist = False
    multiComposer = False
    multiArranger = False

    if ';' in (line[5]):
        multiArtist = True
        json_artists = []

        multiArtistsJa = line[5].split(';')
        multiArtistsRom = line[6].split(';')
        multiArtistsKo = line[7].split(';')

        for i in range(len(multiArtistsJa)):
            json_artists.append({'ja': multiArtistsJa[i], 'rom': multiArtistsRom[i], 'ko': multiArtistsKo[i]})

    if ';' in (line[8]):
        multiLyricist = True
        json_lyricists = []

        multiLyricistsJa = line[8].split(';')
        multiLyricistsRom = line[9].split(';')
        multiLyricistsKo = line[10].split(';')

        for i in range(len(multiLyricistsJa)):
            json_lyricists.append({'ja': multiLyricistsJa[i], 'rom': multiLyricistsRom[i], 'ko': multiLyricistsKo[i]})

    if ';' in (line[11]):
        multiComposer = True
        json_composers = []

        multiComposersJa = line[11].split(';')
        multiComposersRom = line[12].split(';')
        multiComposersKo = line[13].split(';')

        for i in range(len(multiComposersJa)):
            json_composers.append({'ja': multiComposersJa[i], 'rom': multiComposersRom[i], 'ko': multiComposersKo[i]})

    if ';' in (line[14]):
        multiArranger = True
        json_arrangers = []

        multiArrangersJa = line[14].split(';')
        multiArrangersRom = line[15].split(';')
        multiArrangersKo = line[16].split(';')

        for i in range(len(multiArrangersJa)):
            json_arrangers.append({'ja': multiArrangersJa[i], 'rom': multiArrangersRom[i], 'ko': multiArrangersKo[i]})

    json_songs.append({'track': line[1], 'title': {'ja': line[2], 'rom': line[3], 'ko': line[4]}, 'artist': json_artists if multiArtist else {'ja': line[5], 'rom': line[6], 'ko': line[7]}, 'lyricist': json_lyricists if multiLyricist else {'ja': line[8], 'rom': line[9], 'ko': line[10]}, 'composer': json_composers if multiComposer else {'ja': line[11], 'rom': line[12], 'ko': line[13]}, 'arranger': json_arrangers if multiArranger else {'ja': line[14], 'rom': line[15], 'ko': line[16]}, 'link': line[18], 'note': line[19]})

fr_csv = open(input, 'r', encoding='utf-8')
rdr = csv.reader(fr_csv)
next(rdr)

for line in rdr:
    if line[0] != currentAlbum:

        currentAlbum = line[0]

        if len(json_songs) > 0:
            json_album['songs'] = json_songs
            json_data.append(json_album)
        
            json_album = OrderedDict()
            json_songs = []

        json_album['album'] = currentAlbum
        json_album['release'] = line[17]
                
        addSong(line)
    else:
        addSong(line)

json_album['songs'] = json_songs
json_data.append(json_album)
#print(json.dumps(json_data, ensure_ascii=False, indent="\t"))

with open(output, 'w', encoding='utf-8') as make_file:
    json.dump(json_data, make_file, ensure_ascii=False, indent="\t")
    print("Extract complete")