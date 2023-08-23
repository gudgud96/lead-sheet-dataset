# -*- coding: utf-8 -*-

import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import os
import time
import json
import re
import random
import xmltodict
import string
import traceback
import pickle

website = 'https://www.hooktheory.com'
api_website = 'https://api.hooktheory.com/v1/songs/public/[song_id]?fields=ID,xmlData,song,jsonData'
base_url = website + '/theorytab/artists/'
genre_url = '/wiki/[genre_id]/genres'
# alphabet_list = string.ascii_lowercase
alphabet_list = 'abcdefghijklmnopqrstuvwxyz0123456789'
root_dir = '../datasets'
root_xml = '../datasets/xml'


MODES = [
    "major",
    "dorian",
    "phrygian",
    "lydian",
    "mixolydian",
    "minor",
    "locrian",
]

BORROWED_SCALES = {
    1: "lydian",
    0: "major",
    -1: "mixolydian",
    -2: "dorian",
    -3: "minor",
    -4: "phrygian",
    -5: "locrian",
}


def map_notes_to_new_format(notes):
    """
    old format keys:
        start_beat_abs, start_measure, start_beat, note_length,
        scale_degree, octave, isRest

    new format keys:
        sd, octave, beat, duration, isRest, recordingEndBeat
    """
    new_notes = [
        "sd", "octave", "beat", "duration", "isRest", "recordingEndBeat"
    ]

    res_lst = []
    for note in notes:
        res = {k : None for k in new_notes}
        res["sd"] = note["scale_degree"]
        res["octave"] = int(note["octave"])
        res["beat"] = float(note["start_beat_abs"])
        res["duration"] = float(note["note_length"])
        res["isRest"] = True if note["isRest"] == "1" else False
        res["recordingEndBeat"] = None

        res_lst.append(res)

    return res_lst


def map_chords_to_new_format(chords):
    """
    HookTheory still keeps 2 formats of chords.
    Convert old version chord to new version.

    old format keys: 
        sd, fb (tension and inversion), sec, sus, pedal, alternate, borrowed, 
        chord_duration, start_measure, start_beat, 
        start_beat_abs, isRest
    
    new format keys:
        root, beat, duration, type, inversion, applied,
        adds, omits, alterations, suspensions, pedal,
        alternate, borrowed, isRest, recordingEndBeat
    """
    new_chords = [
        "root", "beat", "duration", "type", "inversion", 
        "applied", "adds", "omits", "alterations", "suspensions", 
        "pedal", "alternate", "borrowed", "isRest", "recordingEndBeat"
    ]

    res_lst = []
    for chord in chords:
        res = {k : None for k in new_chords}
        if chord["sd"] == "rest":
            res["root"] = 1
        else:
            res["root"] = int(chord["sd"])
        res["beat"] = float(chord["start_beat_abs"])
        res["duration"] = float(chord["chord_duration"])
        
        # refer to `set_composition` in `roman_to_symbol.py`
        fb = chord["fb"]
        if fb in [None, '6', '64']:
            chord_type = 5
        elif fb in ['7', '65', '43', '42']:
            chord_type = 7
        else:
            chord_type = int(fb)
        res["type"] = chord_type

        # NOTE: ignore inversion and applied for now
        res["inversion"] = 0
        res["applied"] = 0

        # adds and omits
        # refer to `set_emb` in `roman_to_symbol.py`
        res["adds"] = []
        res["omits"] = []
        if 'emb' in chord:
            emb = chord['emb']
            if emb is not None:
                for emb_event in emb:
                    if emb_event == 'add9':
                        res["adds"].append(9)
                    elif emb_event == 'add11':
                        res["adds"].append(11)
                    elif emb_event == 'add13':
                        res["adds"].append(13)
                    elif emb_event == 'no3':
                        res["omits"].append(3)
                    elif emb_event == 'no5':
                        res["omits"].append(5)
            
        # alternate
        res["alterations"] = []
        # refer to `set_alter` in `roman_to_symbol.py`
        if chord["alternate"] is not None:
            res["alterations"] = chord["alternate"]

        # suspension
        res["suspensions"] = []
        if chord["sus"] == "sus2":
            res["suspensions"].append(2)
        elif chord["sus"] == "sus4":
            res["suspensions"].append(4)
        elif chord["sus"] == "sus24":
            res["suspensions"].append(2)
            res["suspensions"].append(4)
        
        # pedal
        res["pedal"] = chord["pedal"]
        
        # borrowed
        res["borrowed"] = ""
        borrowed = chord["borrowed"]
        if borrowed is not None:
            # refer to `is_int` in `roman_to_symbol.py`
            try:
                borrowed = int(borrowed)
            except ValueError:
                if borrowed == 'b':
                    borrowed = -3
            borrowed = min(max(borrowed, -5), 1)
            res["borrowed"] = BORROWED_SCALES[borrowed]

        # isRest
        res["isRest"] = True if chord["isRest"] == "1" else False

        res_lst.append(res)

    return res_lst


def xml_to_json(xml):
    # TODO: fix chords, notes, fix str and float etc.
    dict = xmltodict.parse(xml)
    # with open("test.json", "w+") as f:
    #     json.dump(dict, f, indent=4)
    res = {}
    dict = dict["theorytab"]

    res["version"] = dict["version"]
    segment = dict["data"]["segment"]
    # NOTE: I find for some cases, `segment` is a list,
    # but all items in the list are the same. So I simply pick the first item.
    if type(segment) == list:
        segment = segment[0]
    elif type(segment) == dict:
        pass

    res["chords"] = []
    res["notes"] = []
    if "harmony" in segment:
        if "chord" in segment["harmony"]:
            res["chords"] = map_chords_to_new_format(segment["harmony"]["chord"])
    if "melody" in segment:
        if "voice" in segment["melody"] and len(segment["melody"]["voice"]) > 0:
            voice = segment["melody"]["voice"][0]
            if "notes" in voice:
                if voice["notes"] is not None:
                    if "note" in voice["notes"]:
                        res["notes"] = map_notes_to_new_format(voice["notes"]["note"])
    
    res["keys"] = [{}]
    res["keys"][0]["beat"] = 1
    res["keys"][0]["scale"] = MODES[int(dict["meta"]["mode"]) - 1]
    res["keys"][0]["tonic"] = dict["meta"]["key"]

    res["tempos"] = [{}]
    res["tempos"][0]["beat"] = 1
    res["tempos"][0]["bpm"] = int(dict["meta"]["BPM"])
    res["tempos"][0]["swingFactor"] = 0
    res["tempos"][0]["swingBeat"] = 0

    res["meters"] = [{}]
    res["meters"][0]["beat"] = 1
    res["meters"][0]["numBeats"] = int(dict["meta"]["beats_in_measure"])
    res["meters"][0]["beatUnit"] = 0

    res["youtube"] = {
        "id": dict["meta"]["YouTubeID"],
        "syncStart": float(dict["meta"]["active_start"]),
        "syncEnd": float(dict["meta"]["active_stop"]),
        "syncMode": "youtube-sync-mode-test"
    }

    return res


def song_retrieval(song_url, path_song):
    response = requests.get(website + song_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    section_list = [item['href'].split('#')[-1] for item in soup.find_all('a', {'href': re.compile(song_url+'#')})]
    song_id_list = [item['href'].split('#')[-1] for item in soup.find_all('a', {'href': re.compile("idOfSong=")})]
    for i in range(len(song_id_list)):
        song_id = song_id_list[i]
        song_id = re.search("idOfSong=(.)+&enable", song_id).group(0)
        song_id = song_id.replace("idOfSong=", "").replace("&enable", "")
        song_id_list[i] = song_id

    genre_id = soup.findAll("multiselect", {"items": "genres"})[0]['wikiid']
    response = requests.get(website + genre_url.replace("[genre_id]", genre_id))
    dict = json.loads(response.text)
    genres_dict = []
    for genre in dict:
        if genre['active']:
            genres_dict.append(genre)

    assert len(section_list) == len(song_id_list)

    res = {}
    res["url"] = website + song_url
    res["sections"] = {}
    is_xml = False
    for i in range(len(song_id_list)):
        res["sections"][section_list[i]] = {}
        song_id = song_id_list[i]
        res["sections"][section_list[i]]["songId"] = song_id
        response = requests.get(api_website.replace("[song_id]", song_id))

        dict = json.loads(response.text)
        res["sections"][section_list[i]]["songIdNum"] = dict["ID"]
        res["name"] = dict["song"]
        if dict["jsonData"] is not None:
            res["sections"][section_list[i]]["jsonData"] = json.loads(dict["jsonData"])
        else:
            is_xml = True
            xmlDataDict = xml_to_json(dict["xmlData"])            
            res["sections"][section_list[i]]["jsonData"] = xmlDataDict

    res["genres"] = genres_dict

    if not os.path.exists(path_song):
        os.makedirs(path_song)
    if is_xml:
        # NOTE: we keep a list of urls which uses old xml format
        with open(os.path.join(root_dir, "old_xml_format.txt"), "a+") as f:
            f.write(song_url + "\n")
    with open(os.path.join(path_song, 'song_info.json'), "w") as f:
        json.dump(res, f, indent=4)


def get_song_list(url_artist, quite=False):
    response_tmp = requests.get(website + url_artist)
    soup = BeautifulSoup(response_tmp.text, 'html.parser')
    item_list = soup.find_all("li", {"class": re.compile("overlay-trigger")})

    song_name_list = []
    for item in item_list:
        song_name = item.find_all("a", {"class": "a-no-decoration"})[0]['href'].split('/')[-1]
        song_name_list.append(song_name)
        if not quite:
            print('   > %s' % song_name)
    return song_name_list


def traverse_website(ch):
    '''
    Retrieve all urls of artists and songs from the website
    '''

    list_pages = []
    archive_artist = dict()
    artist_count = 0
    song_count = 0

    sleep_time = random.uniform(0.2, 0.6)
    time.sleep(sleep_time)
    url = base_url + ch
    response_tmp = requests.get(url)
    soup = BeautifulSoup(response_tmp.text, 'html.parser')
    page_count = 0

    print('==[%c]=================================================' % ch)

    # get artists list by pages
    url_artist_list = []
    for page in range(1, 9999):
        url = 'https://www.hooktheory.com/theorytab/artists/'+ch+'?page=' + str(page)
        print(url)
        time.sleep(sleep_time)
        response_tmp = requests.get(url)
        soup = BeautifulSoup(response_tmp.text, 'html.parser')
        item_list = soup.find_all("li", {"class": re.compile("overlay-trigger")})

        if item_list:
            page_count += 1
        else:
            break

        for item in item_list:
            url_artist_list.append(item.find_all("a", {"class": "a-no-decoration"})[0]['href'])

    print('Total:', len(url_artist_list))

    print('----')

    if not page_count:
        page_count = 1

    # get song of artists
    artist_song_dict = dict()

    for url_artist in url_artist_list:
        artist_count += 1
        time.sleep(sleep_time)
        artist_name = url_artist.split('/')[-1]
        print(artist_name)
        song_name_list = get_song_list(url_artist)
        song_count += len(song_name_list)
        artist_song_dict[artist_name] = song_name_list

    archive_artist[ch] = artist_song_dict
    list_pages.append(page_count)

    print('=======================================================')
    print(list_pages)
    print('Artists:', artist_count)
    print('Songs:', song_count)

    archive_artist['num_song'] = song_count
    archive_artist['num_artist'] = artist_count

    return archive_artist


if __name__ == '__main__':

    # song_retrieval("/theorytab/view/chumbawamba/amnesia", "./")

    if not os.path.exists(root_dir):
        os.makedirs(root_dir)

    if not os.path.exists(root_xml):
        os.makedirs(root_xml)

    for ch in alphabet_list:
        archive_artist = traverse_website(ch)

        path_artists = os.path.join(root_dir, 'archive_artist.json')
        with open(path_artists, "w") as f:
            json.dump(archive_artist, f)

        with open(path_artists, "r") as f:
            archive_artist = json.load(f)

        count_ok = 0
        song_count = archive_artist['num_song']
        
        path_ch = os.path.join(root_xml, ch)
        print('==[%c]=================================================' % ch)
        
        if not os.path.exists(path_ch):
            os.makedirs(path_ch)

        for a_name in archive_artist[ch].keys():
            for s_name in archive_artist[ch][a_name]:

                try:
                    print('(%3d/%3d) %s   %s' % (count_ok, song_count, a_name, s_name))
                    path_song = os.path.join(path_ch, a_name, s_name)

                    sleep_time = random.uniform(0.2, 0.6)
                    time.sleep(sleep_time)
                    song_url = '/theorytab/view/' + a_name + '/' + s_name
                    song_retrieval(song_url, path_song)

                    count_ok += 1

                except Exception as e:
                    print(song_url, str(e))

    print('total:', count_ok)