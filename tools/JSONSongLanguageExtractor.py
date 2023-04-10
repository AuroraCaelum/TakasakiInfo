import sys, csv, json
from collections import OrderedDict

if len(sys.argv) == 2:
    input = './../songs/' + sys.argv[1] + '/' + sys.argv[1] + '.csv'
    output = './../songs/' + sys.argv[1] + '/' + sys.argv[1]
elif len(sys.argv) == 3:
    input = sys.argv[1]
    output = sys.argv[2] # Do not include .json extension - EXAMPLE: ./../songs/Nijigaku
else:
    print("Insufficient arguments")
    sys.exit()

json_data_ja = []
json_data_rom = []
json_data_ko = []
json_data_ja_rom = []
json_data_ja_ko = []
json_data_rom_ko = []

currentAlbum = None

def addSong(line):
    multiArtist = False
    multiLyricist = False
    multiComposer = False
    multiArranger = False

    if ';' in (line[3]):
        multiArtist = True
        json_artistsJa = []
        json_artistsRom = []
        json_artistsKo = []

        multiArtistsJa = line[3].split(';')
        multiArtistsRom = line[4].split(';')
        multiArtistsKo = line[5].split(';')

        for i in range(len(multiArtistsJa)):
            json_artistsJa.append(multiArtistsJa[i])
            json_artistsRom.append(multiArtistsRom[i])
            json_artistsKo.append(multiArtistsKo[i])

    if ';' in (line[6]):
        multiLyricist = True
        json_lyricistsJa = []
        json_lyricistsRom = []
        json_lyricistsKo = []

        multiLyricistsJa = line[6].split(';')
        multiLyricistsRom = line[7].split(';')
        multiLyricistsKo = line[8].split(';')

        for i in range(len(multiLyricistsJa)):
            json_lyricistsJa.append(multiLyricistsJa[i])
            json_lyricistsRom.append(multiLyricistsRom[i])
            json_lyricistsKo.append(multiLyricistsKo[i])

    if ';' in (line[9]):
        multiComposer = True
        json_composersJa = []
        json_composersRom = []
        json_composersKo = []

        multiComposersJa = line[9].split(';')
        multiComposersRom = line[10].split(';')
        multiComposersKo = line[11].split(';')

        for i in range(len(multiComposersJa)):
            json_composersJa.append(multiComposersJa[i])
            json_composersRom.append(multiComposersRom[i])
            json_composersKo.append(multiComposersKo[i])

    if ';' in (line[12]):
        multiArranger = True
        json_arrangersJa = []
        json_arrangersRom = []
        json_arrangersKo = []

        multiArrangersJa = line[12].split(';')
        multiArrangersRom = line[13].split(';')
        multiArrangersKo = line[14].split(';')

        for i in range(len(multiArrangersJa)):
            json_arrangersJa.append(multiArrangersJa[i])
            json_arrangersRom.append(multiArrangersRom[i])
            json_arrangersKo.append(multiArrangersKo[i])

    json_data_ja.append({'title': line[0], 'artist': json_artistsJa if multiArtist else line[3], 'lyricist': json_lyricistsJa if multiLyricist else line[6], 'composer': json_composersJa if multiComposer else line[9], 'arranger': json_arrangersJa if multiArranger else line[12], 'release': line[16], 'link': line[17], 'note': line[18]})
    json_data_rom.append({'title': line[1], 'artist': json_artistsRom if multiArtist else line[4], 'lyricist': json_lyricistsRom if multiLyricist else line[7], 'composer': json_composersRom if multiComposer else line[10], 'arranger': json_arrangersRom if multiArranger else line[13], 'release': line[16], 'link': line[17], 'note': line[18]})
    json_data_ko.append({'title': line[2], 'artist': json_artistsKo if multiArtist else line[5], 'lyricist': json_lyricistsKo if multiLyricist else line[8], 'composer': json_composersKo if multiComposer else line[11], 'arranger': json_arrangersKo if multiArranger else line[14], 'release': line[16], 'link': line[17], 'note': line[18]})

def addSongMulti(line):
    multiArtist = False
    multiLyricist = False
    multiComposer = False
    multiArranger = False

    if ';' in (line[3]):
        multiArtist = True
        json_artists_ja_rom = []
        json_artists_ja_ko = []
        json_artists_rom_ko = []

        multiArtistsJa = line[3].split(';')
        multiArtistsRom = line[4].split(';')
        multiArtistsKo = line[5].split(';')

        for i in range(len(multiArtistsJa)):
            json_artists_ja_rom.append({'ja': multiArtistsJa[i], 'rom': multiArtistsRom[i]})
            json_artists_ja_ko.append({'ja': multiArtistsJa[i], 'ko': multiArtistsKo[i]})
            json_artists_rom_ko.append({'rom': multiArtistsRom[i], 'ko': multiArtistsKo[i]})

    if ';' in (line[6]):
        multiLyricist = True
        json_lyricists_ja_rom = []
        json_lyricists_ja_ko = []
        json_lyricists_rom_ko = []

        multiLyricistsJa = line[6].split(';')
        multiLyricistsRom = line[7].split(';')
        multiLyricistsKo = line[8].split(';')

        for i in range(len(multiLyricistsJa)):
            json_lyricists_ja_rom.append({'ja': multiLyricistsJa[i], 'rom': multiLyricistsRom[i]})
            json_lyricists_ja_ko.append({'ja': multiLyricistsJa[i], 'ko': multiLyricistsKo[i]})
            json_lyricists_rom_ko.append({'rom': multiLyricistsRom[i], 'ko': multiLyricistsKo[i]})

    if ';' in (line[9]):
        multiComposer = True
        json_composers_ja_rom = []
        json_composers_ja_ko = []
        json_composers_rom_ko = []

        multiComposersJa = line[9].split(';')
        multiComposersRom = line[10].split(';')
        multiComposersKo = line[11].split(';')

        for i in range(len(multiComposersJa)):
            json_composers_ja_rom.append({'ja': multiComposersJa[i], 'rom': multiComposersRom[i]})
            json_composers_ja_ko.append({'ja': multiComposersJa[i], 'ko': multiComposersKo[i]})
            json_composers_rom_ko.append({'rom': multiComposersRom[i], 'ko': multiComposersKo[i]})

    if ';' in (line[12]):
        multiArranger = True
        json_arrangers_ja_rom = []
        json_arrangers_ja_ko = []
        json_arrangers_rom_ko = []

        multiArrangersJa = line[12].split(';')
        multiArrangersRom = line[13].split(';')
        multiArrangersKo = line[14].split(';')

        for i in range(len(multiArrangersJa)):
            json_arrangers_ja_rom.append({'ja': multiArrangersJa[i], 'rom': multiArrangersRom[i]})
            json_arrangers_ja_ko.append({'ja': multiArrangersJa[i], 'ko': multiArrangersKo[i]})
            json_arrangers_rom_ko.append({'rom': multiArrangersRom[i], 'ko': multiArrangersKo[i]})

    json_data_ja_rom.append({'title': {'ja': line[0], 'rom': line[1]}, 'artist': json_artists_ja_rom if multiArtist else {'ja': line[3], 'rom': line[4]}, 'lyricist': json_lyricists_ja_rom if multiLyricist else {'ja': line[6], 'rom': line[7]}, 'composer': json_composers_ja_rom if multiComposer else {'ja': line[9], 'rom': line[10]}, 'arranger': json_arrangers_ja_rom if multiArranger else {'ja': line[12], 'rom': line[13]}, 'release': line[16], 'link': line[17], 'note': line[18]})
    json_data_ja_ko.append({'title': {'ja': line[0], 'ko': line[2]}, 'artist': json_artists_ja_ko if multiArtist else {'ja': line[3], 'ko': line[5]}, 'lyricist': json_lyricists_ja_ko if multiLyricist else {'ja': line[6], 'ko': line[8]}, 'composer': json_composers_ja_ko if multiComposer else {'ja': line[9], 'ko': line[11]}, 'arranger': json_arrangers_ja_ko if multiArranger else {'ja': line[12], 'ko': line[14]}, 'release': line[16], 'link': line[17], 'note': line[18]})
    json_data_rom_ko.append({'title': {'rom': line[1], 'ko': line[2]}, 'artist': json_artists_rom_ko if multiArtist else {'rom': line[4], 'ko': line[5]}, 'lyricist': json_lyricists_rom_ko if multiLyricist else {'rom': line[7], 'ko': line[8]}, 'composer': json_composers_rom_ko if multiComposer else {'rom': line[10], 'ko': line[11]}, 'arranger': json_arrangers_rom_ko if multiArranger else {'rom': line[13], 'ko': line[14]}, 'release': line[16], 'link': line[17], 'note': line[18]})


fr_csv = open(input, 'r', encoding='utf-8')
rdr = csv.reader(fr_csv)
next(rdr)

for line in rdr:
    addSong(line)
    addSongMulti(line)

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