from flask import Flask, request, redirect, render_template
import requests
import base64
import urllib.parse
from datetime import datetime
import os
import logging

CLIENT_ID = os.environ.get('CLIENT_ID')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
REDIRECT_URI = os.environ.get('REDIRECT_URI')

app = Flask(__name__)
session_cache = {}

# === Camelot変換関数 ===
def key_to_camelot(key, mode):
    camelot_map = {
        0: '8B', 1: '3B', 2: '10B', 3: '5B', 4: '12B', 5: '7B',
        6: '2B', 7: '9B', 8: '4B', 9: '11B', 10: '6B', 11: '1B'
    }
    camelot_map_minor = {
        0: '5A', 1: '12A', 2: '7A', 3: '2A', 4: '9A', 5: '4A',
        6: '11A', 7: '6A', 8: '1A', 9: '8A', 10: '3A', 11: '10A'
    }
    return camelot_map.get(key, '') if mode == 1 else camelot_map_minor.get(key, '')

@app.route('/')
def login():
    scopes = 'user-follow-read'
    auth_url = 'https://accounts.spotify.com/authorize?' + urllib.parse.urlencode({
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'scope': scopes,
        'redirect_uri': REDIRECT_URI
    })
    return redirect(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_url = 'https://accounts.spotify.com/api/token'
    headers = {
        'Authorization': 'Basic ' + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode(),
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI
    }
    res = requests.post(token_url, data=data, headers=headers)
    token = res.json().get('access_token')

    if not token:
        return f"Error: {res.json()}"

    return redirect(f'/albums?token={token}')

def get_all_followed_artists(token):
    url = 'https://api.spotify.com/v1/me/following'
    headers = {'Authorization': f'Bearer {token}'}
    params = {'type': 'artist', 'limit': 20}

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        data = res.json().get('artists', {})
        return data.get('items', [])
    except requests.exceptions.RequestException as e:
        logging.error(f"Spotify API error: {e}")
        return []

# ページリストを生成する関数
def build_page_list(current, total):
    pages = []
    if total <= 7:
        pages = list(range(1, total + 1))
    else:
        pages.append(1)
        if current - 2 > 2:
            pages.append('…')
        for i in range(current - 2, current + 3):
            if 1 < i < total:
                pages.append(i)
        if current + 2 < total - 1:
            pages.append('…')
        pages.append(total)
    return pages

@app.route('/albums')
def albums():
    token = request.args.get('token')
    page = int(request.args.get('page', 1))
    per_page = 10

    if token in session_cache:
        all_albums = session_cache[token]
    else:
        artists = get_all_followed_artists(token)
        all_albums = []
        for artist in artists[:10]:  # 最初の10件のみ取得
            album_url = f'https://api.spotify.com/v1/artists/{artist["id"]}/albums'
            params = {'include_groups': 'album,single', 'limit': 3, 'market': 'JP'}
            try:
                res = requests.get(album_url, headers={'Authorization': f'Bearer {token}'}, params=params, timeout=10)
                res.raise_for_status()
                for album in res.json().get('items', []):
                    all_albums.append({
                        'id': album['id'],
                        'artist': artist['name'],
                        'title': album['name'],
                        'release_date': album['release_date'],
                        'type': album['album_type'],
                        'image_url': album['images'][0]['url'] if album.get('images') else ''
                    })
            except requests.exceptions.RequestException as e:
                logging.error(f"Error fetching albums for artist {artist['name']}: {e}")
        all_albums.sort(key=lambda x: x['release_date'], reverse=True)
        session_cache[token] = all_albums

    start = (page - 1) * per_page
    end = start + per_page
    total_pages = (len(all_albums) + per_page - 1) // per_page
    page_list = build_page_list(page, total_pages)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    return render_template('index.html', albums=all_albums[start:end], page=page, total_pages=total_pages, token=token, page_list=page_list, timestamp=timestamp)

@app.route('/album/<album_id>')
def album(album_id):
    token = request.args.get('token')
    page = request.args.get('page', 1)
    headers = {'Authorization': f'Bearer {token}'}

    album_url = f'https://api.spotify.com/v1/albums/{album_id}'
    album_res = requests.get(album_url, headers=headers).json()
    tracks = album_res.get('tracks', {}).get('items', [])

    for track in tracks:
        track_id = track.get('id')
        if not track_id:
            continue

        try:
            res = requests.get(f'https://api.spotify.com/v1/audio-features/{track_id}', headers=headers)
            if res.status_code == 200:
                f = res.json()
                tempo = f.get('tempo')
                key = f.get('key')
                mode = f.get('mode')
                track['bpm'] = round(tempo) if tempo else ''
                track['key'] = key if key is not None else ''
                track['mode'] = mode if mode is not None else ''
                track['camelot'] = key_to_camelot(key, mode) if key is not None and mode is not None else ''
            else:
                track['bpm'] = track['key'] = track['mode'] = track['camelot'] = ''
        except Exception as e:
            track['bpm'] = track['key'] = track['mode'] = track['camelot'] = ''

    return render_template('album.html', album=album_res, tracks=tracks, page=page, token=token)

if __name__ == '__main__':
    app.run(debug=True)
