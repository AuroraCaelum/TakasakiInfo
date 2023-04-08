import sys, csv

# MODE 0    [song]    ja = [line[0],line[3],line[6],line[9],line[12],line[15],line[16],line[17],line[18]]
# MODE 1    [song]    rom = [line[1],line[4],line[7],line[10],line[13],line[15],line[16],line[17],line[18]]
# MODE 2    [song]    ko = [line[2],line[5],line[8],line[11],line[14],line[15],line[16],line[17],line[18]]
# MODE 3    [song]    ja-rom = [line[0],line[1],line[3],line[4],line[6],line[7],line[9],line[10],line[12],line[13],line[15],line[16],line[17],line[18]]
# MODE 4    [song]    ja-ko = [line[0],line[2],line[3],line[5],line[6],line[8],line[9],line[11],line[12],line[14],line[15],line[16],line[17],line[18]]
# MODE 5    [song]    rom-ko = [line[1],line[2],line[4],line[5],line[7],line[8],line[10],line[11],line[13],line[14],line[15],line[16],line[17],line[18]]

if len(sys.argv) != 4:
    print("Insufficient arguments")
    sys.exit()
    
input = sys.argv[1]
output = sys.argv[2]

def modeStr(key):
    modeNum = {'ja' : 0, 'rom' : 1, 'ko' : 2, 'ja-rom' : 3, 'ja-ko' : 4, 'rom-ko' : 5}.get(key, -1)
    if modeNum == -1:
        return int(key)
    else:
        return modeNum

mode = modeStr(sys.argv[3])

if mode >= 0 and mode <= 5:
    fr = open(input, 'r', encoding='utf-8')
    rdr = csv.reader(fr)

    fw = open(output, 'w', encoding='utf-8', newline='')
    wr = csv.writer(fw)

    def modeSelect(key):
        modeTemplate = {0 : [line[0],line[3],line[6],line[9],line[12],line[15],line[16],line[17],line[18]],
        1 : [line[1],line[4],line[7],line[10],line[13],line[15],line[16],line[17],line[18]],
        2 : [line[2],line[5],line[8],line[11],line[14],line[15],line[16],line[17],line[18]],
        3 : [line[0],line[1],line[3],line[4],line[6],line[7],line[9],line[10],line[12],line[13],line[15],line[16],line[17],line[18]],
        4 : [line[0],line[2],line[3],line[5],line[6],line[8],line[9],line[11],line[12],line[14],line[15],line[16],line[17],line[18]],
        5 : [line[1],line[2],line[4],line[5],line[7],line[8],line[10],line[11],line[13],line[14],line[15],line[16],line[17],line[18]]}.get(key, -1)
        return modeTemplate

    def modeName(key):
        return {0 : 'ja', 1 : 'rom', 2 : 'ko', 3 : 'ja-rom', 4 : 'ja-ko', 5 : 'rom-ko'}.get(key, -1)

    for line in rdr:
        wr.writerow(modeSelect(mode))
    fr.close()
    fw.close()

    print("New CSV File in mode '" + modeName(mode) + "' is successfully created.")
else:
    print("Invalid mode")
    sys.exit()