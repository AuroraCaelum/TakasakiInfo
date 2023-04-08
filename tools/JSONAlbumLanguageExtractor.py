import sys, csv, json
from collections import OrderedDict

if len(sys.argv) != 3:
    print("Insufficient arguments")
    sys.exit()

input = sys.argv[1]
output = sys.argv[2] # Do not include .json extension - EXAMPLE: ./../songs/Nijigaku
# Usage : python JSONAlbumExtractor.py './../albums/Liella/Liella.csv' './../albums/Liella/Liella'

json_data_ja = []
json_data_rom = []
json_data_ko = []
json_data_ja_rom = []
json_data_ja_ko = []
json_data_rom_ko = []

json_album_ja = OrderedDict()
json_album_rom = OrderedDict()
json_album_ko = OrderedDict()
json_album_ja_rom = OrderedDict()
json_album_ja_ko = OrderedDict()
json_album_rom_ko = OrderedDict()

json_songs_ja = []
json_songs_rom = []
json_songs_ko = []
json_songs_ja_rom = []
json_songs_ja_ko = []
json_songs_rom_ko = []


currentAlbum = None

def addSong(line):
    multiArtist = False
    multiLyricist = False
    multiComposer = False
    multiArranger = False

    if ';' in (line[5]):
        multiArtist = True
        json_artistsJa = []
        json_artistsRom = []
        json_artistsKo = []
        json_artists_ja_rom = []
        json_artists_ja_ko = []
        json_artists_rom_ko = []


        multiArtistsJa = line[5].split(';')
        multiArtistsRom = line[6].split(';')
        multiArtistsKo = line[7].split(';')

        for i in range(len(multiArtistsJa)):
            json_artistsJa.append(multiArtistsJa[i])
            json_artistsRom.append(multiArtistsRom[i])
            json_artistsKo.append(multiArtistsKo[i])
            json_artists_ja_rom.append({'ja': multiArtistsJa[i], 'rom': multiArtistsRom[i]})
            json_artists_ja_ko.append({'ja': multiArtistsJa[i], 'ko': multiArtistsKo[i]})
            json_artists_rom_ko.append({'rom': multiArtistsRom[i], 'ko': multiArtistsKo[i]})

    if ';' in (line[8]):
        multiLyricist = True
        json_lyricistsJa = []
        json_lyricistsRom = []
        json_lyricistsKo = []
        json_lyricists_ja_rom = []
        json_lyricists_ja_ko = []
        json_lyricists_rom_ko = []

        multiLyricistsJa = line[8].split(';')
        multiLyricistsRom = line[9].split(';')
        multiLyricistsKo = line[10].split(';')

        for i in range(len(multiLyricistsJa)):
            json_lyricistsJa.append(multiLyricistsJa[i])
            json_lyricistsRom.append(multiLyricistsRom[i])
            json_lyricistsKo.append(multiLyricistsKo[i])
            json_lyricists_ja_rom.append({'ja': multiLyricistsJa[i], 'rom': multiLyricistsRom[i]})
            json_lyricists_ja_ko.append({'ja': multiLyricistsJa[i], 'ko': multiLyricistsKo[i]})
            json_lyricists_rom_ko.append({'rom': multiLyricistsRom[i], 'ko': multiLyricistsKo[i]})

    if ';' in (line[11]):
        multiComposer = True
        json_composersJa = []
        json_composersRom = []
        json_composersKo = []
        json_composers_ja_rom = []
        json_composers_ja_ko = []
        json_composers_rom_ko = []

        multiComposersJa = line[11].split(';')
        multiComposersRom = line[12].split(';')
        multiComposersKo = line[13].split(';')

        for i in range(len(multiComposersJa)):
            json_composersJa.append(multiComposersJa[i])
            json_composersRom.append(multiComposersRom[i])
            json_composersKo.append(multiComposersKo[i])
            json_composers_ja_rom.append({'ja': multiComposersJa[i], 'rom': multiComposersRom[i]})
            json_composers_ja_ko.append({'ja': multiComposersJa[i], 'ko': multiComposersKo[i]})
            json_composers_rom_ko.append({'rom': multiComposersRom[i], 'ko': multiComposersKo[i]})

    if ';' in (line[14]):
        multiArranger = True
        json_arrangersJa = []
        json_arrangersRom = []
        json_arrangersKo = []
        json_arrangers_ja_rom = []
        json_arrangers_ja_ko = []
        json_arrangers_rom_ko = []

        multiArrangersJa = line[14].split(';')
        multiArrangersRom = line[15].split(';')
        multiArrangersKo = line[16].split(';')

        for i in range(len(multiArrangersJa)):
            json_arrangersJa.append(multiArrangersJa[i])
            json_arrangersRom.append(multiArrangersRom[i])
            json_arrangersKo.append(multiArrangersKo[i])
            json_arrangers_ja_rom.append({'ja': multiArrangersJa[i], 'rom': multiArrangersRom[i]})
            json_arrangers_ja_ko.append({'ja': multiArrangersJa[i], 'ko': multiArrangersKo[i]})
            json_arrangers_rom_ko.append({'rom': multiArrangersRom[i], 'ko': multiArrangersKo[i]})

    json_songs_ja.append({'track': line[1], 'title': line[2], 'artist': json_artistsJa if multiArtist else line[5], 'lyricist': json_lyricistsJa if multiLyricist else line[8], 'composer': json_composersJa if multiComposer else line[11], 'arranger': json_arrangersJa if multiArranger else line[14], 'link': line[18], 'note': line[19]})
    json_songs_rom.append({'track': line[1], 'title': line[3], 'artist': json_artistsRom if multiArtist else line[6], 'lyricist': json_lyricistsRom if multiLyricist else line[9], 'composer': json_composersRom if multiComposer else line[12], 'arranger': json_arrangersRom if multiArranger else line[15], 'link': line[18], 'note': line[19]})
    json_songs_ko.append({'track': line[1], 'title': line[4], 'artist': json_artistsKo if multiArtist else line[7], 'lyricist': json_lyricistsKo if multiLyricist else line[10], 'composer': json_composersKo if multiComposer else line[13], 'arranger': json_arrangersKo if multiArranger else line[16], 'link': line[18], 'note': line[19]})
    json_songs_ja_rom.append({'track': line[1], 'title': {'ja': line[2], 'rom': line[3]}, 'artist': json_artists_ja_rom if multiArtist else {'ja': line[5], 'rom': line[6]}, 'lyricist': json_lyricists_ja_rom if multiLyricist else {'ja': line[8], 'rom': line[9]}, 'composer': json_composers_ja_rom if multiComposer else {'ja': line[11], 'rom': line[12]}, 'arranger': json_arrangers_ja_rom if multiArranger else {'ja': line[14], 'rom': line[15]}, 'link': line[18], 'note': line[19]})
    json_songs_ja_ko.append({'track': line[1], 'title': {'ja': line[2], 'ko': line[4]}, 'artist': json_artists_ja_ko if multiArtist else {'ja': line[5], 'ko': line[7]}, 'lyricist': json_lyricists_ja_ko if multiLyricist else {'ja': line[8], 'ko': line[10]}, 'composer': json_composers_ja_ko if multiComposer else {'ja': line[11], 'ko': line[13]}, 'arranger': json_arrangers_ja_ko if multiArranger else {'ja': line[14], 'ko': line[16]}, 'link': line[18], 'note': line[19]})
    json_songs_rom_ko.append({'track': line[1], 'title': {'rom': line[3], 'ko': line[4]}, 'artist': json_artists_rom_ko if multiArtist else {'rom': line[6], 'ko': line[7]}, 'lyricist': json_lyricists_rom_ko if multiLyricist else {'rom': line[9], 'ko': line[10]}, 'composer': json_composers_rom_ko if multiComposer else {'rom': line[12], 'ko': line[13]}, 'arranger': json_arrangers_rom_ko if multiArranger else {'rom': line[15], 'ko': line[16]}, 'link': line[18], 'note': line[19]})
    

fr_csv = open(input, 'r', encoding='utf-8')
rdr = csv.reader(fr_csv)
next(rdr)

for line in rdr:
    if line[0] != currentAlbum:

        currentAlbum = line[0]

        if len(json_songs_ja) > 0:
            json_album_ja['songs'] = json_songs_ja
            json_album_rom['songs'] = json_songs_rom
            json_album_ko['songs'] = json_songs_ko
            json_album_ja_rom['songs'] = json_songs_ja_rom
            json_album_ja_ko['songs'] = json_songs_ja_ko
            json_album_rom_ko['songs'] = json_songs_rom_ko

            json_data_ja.append(json_album_ja)
            json_data_rom.append(json_album_rom)
            json_data_ko.append(json_album_ko)
            json_data_ja_rom.append(json_album_ja_rom)
            json_data_ja_ko.append(json_album_ja_ko)
            json_data_rom_ko.append(json_album_rom_ko)
        
            json_album_ja = OrderedDict()
            json_album_rom = OrderedDict()
            json_album_ko = OrderedDict()
            json_album_ja_rom = OrderedDict()
            json_album_ja_ko = OrderedDict()
            json_album_rom_ko = OrderedDict()

            json_songs_ja = []
            json_songs_rom = []
            json_songs_ko = []
            json_songs_ja_rom = []
            json_songs_ja_ko = []
            json_songs_rom_ko = []

        json_album_ja['album'] = currentAlbum
        json_album_rom['album'] = currentAlbum
        json_album_ko['album'] = currentAlbum
        json_album_ja_rom['album'] = currentAlbum
        json_album_ja_ko['album'] = currentAlbum
        json_album_rom_ko['album'] = currentAlbum

        json_album_ja['release'] = line[17]
        json_album_rom['release'] = line[17]
        json_album_ko['release'] = line[17]
        json_album_ja_rom['release'] = line[17]
        json_album_ja_ko['release'] = line[17]
        json_album_rom_ko['release'] = line[17]
                
        addSong(line)
    else:
        addSong(line)

json_album_ja['songs'] = json_songs_ja
json_album_rom['songs'] = json_songs_rom
json_album_ko['songs'] = json_songs_ko
json_album_ja_rom['songs'] = json_songs_ja_rom
json_album_ja_ko['songs'] = json_songs_ja_ko
json_album_rom_ko['songs'] = json_songs_rom_ko

json_data_ja.append(json_album_ja)
json_data_rom.append(json_album_rom)
json_data_ko.append(json_album_ko)
json_data_ja_rom.append(json_album_ja_rom)
json_data_ja_ko.append(json_album_ja_ko)
json_data_rom_ko.append(json_album_rom_ko)

#print(json.dumps(json_data, ensure_ascii=False, indent="\t"))

with open(output + '-ja.json', 'w', encoding='utf-8') as make_file:
    json.dump(json_data_ja, make_file, ensure_ascii=False, indent="\t")
    print("Japanese Extract complete")

with open(output + '-rom.json', 'w', encoding='utf-8') as make_file:
    json.dump(json_data_rom, make_file, ensure_ascii=False, indent="\t")
    print("Romaji Extract complete")

with open(output + '-ko.json', 'w', encoding='utf-8') as make_file:
    json.dump(json_data_ko, make_file, ensure_ascii=False, indent="\t")
    print("Korean Extract complete")

with open(output + '-ja_rom.json', 'w', encoding='utf-8') as make_file:
    json.dump(json_data_ja_rom, make_file, ensure_ascii=False, indent="\t")
    print("Japanese-Romaji Extract complete")

with open(output + '-ja_ko.json', 'w', encoding='utf-8') as make_file:
    json.dump(json_data_ja_ko, make_file, ensure_ascii=False, indent="\t")
    print("Japanese-Korean Extract complete")

with open(output + '-rom_ko.json', 'w', encoding='utf-8') as make_file:
    json.dump(json_data_rom_ko, make_file, ensure_ascii=False, indent="\t")
    print("Romaji-Korean Extract complete")