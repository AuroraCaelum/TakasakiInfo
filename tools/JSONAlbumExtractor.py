import sys, csv, json
from collections import OrderedDict

if len(sys.argv) != 3:
    print("Insufficient arguments")
    sys.exit()

input = sys.argv[1]
output = sys.argv[2]

json_data = []
json_album = OrderedDict()
json_songs = []

currentAlbum = None

def addSong(line):
    multiArtist = False
    multiLyricist = False
    multiComposer = False
    multiArranger = False

    if ';' in (line[3]):
        multiArtist = True
        json_artists = []

        multiArtistsJa = line[3].split(';')
        multiArtistsRom = line[4].split(';')
        multiArtistsKo = line[5].split(';')

        for i in range(len(multiArtistsJa)):
            json_artists.append({'ja': multiArtistsJa[i], 'rom': multiArtistsRom[i], 'ko': multiArtistsKo[i]})

    if ';' in (line[6]):
        multiLyricist = True
        json_lyricists = []

        multiLyricistsJa = line[6].split(';')
        multiLyricistsRom = line[7].split(';')
        multiLyricistsKo = line[8].split(';')

        for i in range(len(multiLyricistsJa)):
            json_lyricists.append({'ja': multiLyricistsJa[i], 'rom': multiLyricistsRom[i], 'ko': multiLyricistsKo[i]})

    if ';' in (line[9]):
        multiComposer = True
        json_composers = []

        multiComposersJa = line[9].split(';')
        multiComposersRom = line[10].split(';')
        multiComposersKo = line[11].split(';')

        for i in range(len(multiComposersJa)):
            json_composers.append({'ja': multiComposersJa[i], 'rom': multiComposersRom[i], 'ko': multiComposersKo[i]})

    if ';' in (line[12]):
        multiArranger = True
        json_arrangers = []

        multiArrangersJa = line[12].split(';')
        multiArrangersRom = line[13].split(';')
        multiArrangersKo = line[14].split(';')

        for i in range(len(multiArrangersJa)):
            json_arrangers.append({'ja': multiArrangersJa[i], 'rom': multiArrangersRom[i], 'ko': multiArrangersKo[i]})

    json_songs.append({'title': {'ja': line[0], 'rom': line[1], 'ko': line[2]}, 'artist': json_artists if multiArtist else {'ja': line[3], 'rom': line[4], 'ko': line[5]}, 'lyricist': json_lyricists if multiLyricist else {'ja': line[6], 'rom': line[7], 'ko': line[8]}, 'composer': json_composers if multiComposer else {'ja': line[9], 'rom': line[10], 'ko': line[11]}, 'arranger': json_arrangers if multiArranger else {'ja': line[12], 'rom': line[13], 'ko': line[14]}, 'link': line[17], 'note': line[18]})

fr_csv = open(input, 'r', encoding='utf-8')
rdr = csv.reader(fr_csv)
next(rdr)

for line in rdr:
    if line[15] != currentAlbum:

        currentAlbum = line[15]

        if len(json_songs) > 0:
            json_album['songs'] = json_songs
            json_data.append(json_album)
        
            json_album = OrderedDict()
            json_songs = []

        json_album['album'] = currentAlbum
        json_album['release'] = line[16]
                
        addSong(line)
    else:
        addSong(line)

json_album['songs'] = json_songs
json_data.append(json_album)
#print(json.dumps(json_data, ensure_ascii=False, indent="\t"))

with open(output, 'w', encoding='utf-8') as make_file:
    json.dump(json_data, make_file, ensure_ascii=False, indent="\t")
    print("Extract complete")