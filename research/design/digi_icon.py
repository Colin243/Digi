"""Deterministic app-icon artwork: original vector-like geometry, no external assets."""
from PIL import Image,ImageDraw
from pathlib import Path
N=2048;im=Image.new('RGB',(N,N),(18,20,20));d=ImageDraw.Draw(im)
def box(rect,rad,color):d.rounded_rectangle(tuple(int(x*2) for x in rect),radius=rad*2,fill=color)
def circle(rect,top,bottom):
    rect=tuple(int(x*2) for x in rect);w=rect[2]-rect[0];h=rect[3]-rect[1]
    g=Image.new('RGB',(w,h));gd=ImageDraw.Draw(g)
    for y in range(h):
        t=y/(h-1);gd.line((0,y,w,y),fill=tuple(round(a*(1-t)+b*t) for a,b in zip(top,bottom)))
    m=Image.new('L',(w,h));ImageDraw.Draw(m).ellipse((0,0,w-1,h-1),fill=255);im.paste(g,rect[:2],m)
box((110,260,914,800),95,(70,74,73));box((124,273,900,786),82,(33,36,36));box((174,233,318,266),12,(181,185,180))
box((180,345,290,399),10,(220,223,212))
for x in range(188,282,13):box((x,351,x+3,393),1,(153,160,152))
circle((354,323,774,743),(235,239,229),(113,119,115));circle((379,348,749,718),(33,37,37),(6,9,9));circle((416,385,712,681),(44,64,70),(7,14,17));circle((460,429,668,637),(27,43,49),(2,5,8));circle((490,455,550,489),(123,155,156),(46,67,70));circle((794,354,822,382),(236,190,104),(207,154,70))
# A drawn D monogram avoids tiny text and system-font dependencies.
box((185,510,208,623),4,(219,225,216));d.arc((180*2,510*2,275*2,623*2),-90,90,fill=(219,225,216),width=23*2)
im.resize((1024,1024),Image.Resampling.LANCZOS).save('ios/Digi/Assets.xcassets/AppIcon.appiconset/Digi-1024.png')
