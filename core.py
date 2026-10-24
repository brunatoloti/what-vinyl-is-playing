import hashlib
import io
import wave
from datetime import datetime
from zoneinfo import ZoneInfo

COLUMNS = ['id', 'identificada_em', 'musica', 'artista', 'album', 'capa_url', 'link', 'chave']
TZ = ZoneInfo('America/Sao_Paulo')


def normalize_result(result):
    apple = result.get('apple_music') or {}
    spotify = result.get('spotify') or {}
    artwork = apple.get('artwork') or {}
    cover = artwork.get('url', '').replace('{w}', '600').replace('{h}', '600')
    images = (spotify.get('album') or {}).get('images') or []
    if not cover and images:
        cover = images[0].get('url', '')
    title = str(result.get('title') or '').strip()
    artist = str(result.get('artist') or '').strip()
    if not title or not artist:
        raise ValueError('O serviço retornou uma identificação incompleta.')
    key = hashlib.sha256(f'{artist.casefold()}|{title.casefold()}'.encode()).hexdigest()
    return {'musica': title, 'artista': artist, 'album': str(result.get('album') or ''),
            'capa_url': cover, 'link': result.get('song_link') or '', 'chave': key}


def pcm_to_wav(pcm, rate=16000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm)
    return output.getvalue()


def recent_duplicate(last, song, now, seconds=600):
    if last.get('chave') != song['chave']:
        return False
    try:
        previous = datetime.fromisoformat(str(last['identificada_em']))
        return previous.tzinfo is not None and 0 <= (now - previous).total_seconds() < seconds
    except (ValueError, TypeError, KeyError):
        return False


def normalize_shazam(payload):
    track = payload.get('track') or {}
    if not track:
        return None
    album = ''
    for section in track.get('sections') or []:
        for item in section.get('metadata') or []:
            if str(item.get('title', '')).casefold() in ('album', 'álbum'):
                album = str(item.get('text') or '')
                break
    song = normalize_result({'title': track.get('title'), 'artist': track.get('subtitle'),
                             'album': album, 'song_link': track.get('url')})
    images = track.get('images') or {}
    song['capa_url'] = images.get('coverarthq') or images.get('coverart') or ''
    return song
