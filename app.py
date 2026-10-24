import asyncio
import html
import threading
import time
import uuid
from collections import deque
from datetime import datetime

import av
import numpy as np
import pandas as pd
from shazamio import Shazam
import streamlit as st
from streamlit_gsheets import GSheetsConnection
from streamlit_webrtc import WebRtcMode, webrtc_streamer

from auth import require_login, logout
from core import COLUMNS, TZ, normalize_shazam, pcm_to_wav, recent_duplicate

st.set_page_config(page_title='Lado A | Seu vinil, agora', page_icon='💿', layout='wide')
st.markdown('''<style>
.stApp {background: radial-gradient(ellipse at top right,#282238 0%,#111318 55%);color:#f1eee8}
[data-testid="stSidebar"] {background:#17191f}
h1,h2,h3 {letter-spacing:-.035em}
.hero-label {color:#c7ac7d;font-size:12px;letter-spacing:.23em;margin:10px 0 20px}
.track-title {font-size:clamp(30px,4vw,62px);line-height:1.05;font-weight:700;margin:18px 0}
.artist {font-size:24px;color:#d2ccc3;margin-bottom:12px}
.album {color:#a39e97;font-size:16px}
.empty-art {aspect-ratio:1;background:repeating-radial-gradient(circle,#151515 0 4px,#232326 5px 7px);border-radius:50%;display:flex;align-items:center;justify-content:center;max-width:480px;box-shadow:0 24px 60px #0007}
.label {background:#c5a978;color:#151515;width:30%;aspect-ratio:1;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:19px;font-weight:bold}
[data-testid="stImage"] img {border-radius:12px;box-shadow:0 22px 55px #0005}
</style>''', unsafe_allow_html=True)


# Stop before creating capture components, connecting to Sheets or exposing data.
require_login()


class AudioBuffer:
    """Bounded, session-specific audio buffer. No Streamlit calls in callback."""
    def __init__(self):
        self.lock = threading.Lock()
        self.parts = deque()
        self.samples = 0
        self.latest = 0.0
        self.resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)

    def receive(self, frame):
        with self.lock:
            for converted in self.resampler.resample(frame):
                chunk = converted.to_ndarray().reshape(-1).astype('<i2').tobytes()
                self.parts.append(chunk)
                self.samples += len(chunk) // 2
            while self.samples > 16000 * 15 and self.parts:
                self.samples -= len(self.parts.popleft()) // 2
            self.latest = time.monotonic()
        return frame

    def clip(self):
        with self.lock:
            if self.samples < 16000 * 10 or time.monotonic() - self.latest > 3:
                return None
            return b''.join(self.parts)[-16000 * 10 * 2:]

    def reset(self):
        with self.lock:
            self.parts.clear()
            self.samples = 0
            self.latest = 0.0
            self.resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)


@st.cache_resource
def sheet_lock():
    return threading.Lock()


def connection():
    return st.connection('gsheets', type=GSheetsConnection)


def history():
    df = connection().read(worksheet='Historico', ttl=0).fillna('')
    if list(df.columns) != COLUMNS:
        raise ValueError('A aba Historico precisa ter os cabeçalhos do arquivo historico_modelo.csv, na mesma ordem.')
    return df.loc[df['id'].astype(str).str.strip() != '', COLUMNS].copy()


def persist(entry):
    # Serializes read/update in this process. Intended for one personal deployment.
    with sheet_lock():
        df = history()
        if entry['id'] in df['id'].astype(str).values:
            return
        if not df.empty and recent_duplicate(df.iloc[-1].to_dict(), entry,
                                              datetime.fromisoformat(entry['identificada_em'])):
            return
        connection().update(worksheet='Historico', data=pd.concat(
            [df, pd.DataFrame([entry], columns=COLUMNS)], ignore_index=True))


def flush_pending(force=False):
    if time.monotonic() < st.session_state.get('save_retry_at', 0) and not force:
        raise RuntimeError('Aguardando nova tentativa de gravação.')
    pending = st.session_state.get('pending', [])
    while pending:
        try:
            persist(pending[0])
        except Exception:
            st.session_state['save_retry_at'] = time.monotonic() + 30
            raise
        pending.pop(0)
        st.session_state['save_retry_at'] = 0


async def recognize_async(wav):
    # Create the client within the event loop used for this recognition.
    return await asyncio.wait_for(Shazam().recognize(wav), timeout=35)


def recognize(wav):
    st.session_state['attempts'] += 1
    try:
        payload = asyncio.run(recognize_async(wav))
        song = normalize_shazam(payload)
        if song is None:
            st.session_state['notice'] = 'Música não identificada neste trecho. A última identificação continua abaixo.'
            return
        now = datetime.now(TZ)
        st.session_state['current'] = {**song, 'identificada_em': now.isoformat(timespec='seconds')}
        st.session_state['notice'] = 'Música identificada.'
        if st.session_state.get('last_key') != song['chave']:
            st.session_state['pending'].append({**song, 'id': str(uuid.uuid4()),
                'identificada_em': now.isoformat(timespec='seconds')})
            st.session_state['last_key'] = song['chave']
    except Exception:
        st.session_state['notice'] = 'Não foi possível consultar o Shazam. A integração não oficial pode estar indisponível ou limitada. Aguarde antes de tentar novamente.'


def display_song():
    song = st.session_state.get('current')
    cover_col, info_col = st.columns([1, 1.3], gap='large')
    with cover_col:
        if song and song.get('capa_url', '').startswith('https://'):
            st.image(song['capa_url'], use_container_width=True)
        else:
            st.markdown('<div class="empty-art"><div class="label">Lado A</div></div>', unsafe_allow_html=True)
    with info_col:
        st.markdown('<div class="hero-label">SEU VINIL, AGORA</div>', unsafe_allow_html=True)
        title = html.escape(song['musica']) if song else 'Deixe o disco tocar.'
        artist = html.escape(song['artista']) if song else 'A próxima descoberta vem da sua coleção.'
        album = html.escape(song['album']) if song else 'Ative o microfone para identificar a música.'
        st.markdown(f'<div class="track-title">{title}</div><div class="artist">{artist}</div><div class="album">{album}</div>', unsafe_allow_html=True)
        if song:
            stamp = datetime.fromisoformat(song['identificada_em'])
            st.caption(f"Última identificação: {stamp:%d/%m/%Y às %H:%M:%S}")
            if song.get('link', '').startswith('https://'):
                st.link_button('Ver música', song['link'])
        st.caption('A capa corresponde ao álbum retornado pelo catálogo e pode variar da edição física do seu vinil.')


for name, value in {'pending': [], 'attempts': 0, 'last_attempt': 0.0,
                    'notice': 'Aguardando o microfone.'}.items():
    if name not in st.session_state:
        st.session_state[name] = value
if 'audio_buffer' not in st.session_state:
    st.session_state['audio_buffer'] = AudioBuffer()

with st.sidebar:
    st.title('Lado A')
    st.caption('O som da sua coleção.')
    if st.session_state.get('pending'):
        st.caption('Há registros pendentes. Aguarde a gravação antes de sair.')
    st.button('Sair', on_click=logout, use_container_width=True)
    page = st.radio('Navegação', ['Tocando agora', 'Histórico'])
    st.divider()
    st.caption('O áudio é processado pelo ShazamIO, que consulta o Shazam para identificação. Nenhuma gravação é salva no histórico.')

if page == 'Tocando agora':
    st.title('O que está no prato?')
    mode = st.radio('Como identificar', ['Automático', 'Por botão'], horizontal=True)
    st.caption('O microfone precisa captar o som das caixas. Autorize o acesso no navegador.')
    if mode == 'Automático':
        interval = st.slider('Intervalo mínimo entre consultas (segundos)', 40, 180, 60, 10)
        st.caption(f'Até {3600 // interval} consultas por hora. Integração gratuita e não oficial, sem garantia de disponibilidade.')
        rtc_config = {'iceServers': [{'urls': ['stun:stun.l.google.com:19302']}]}
        try:
            if 'webrtc' in st.secrets and 'ice_servers' in st.secrets['webrtc']:
                rtc_config = {'iceServers': [dict(item) for item in st.secrets['webrtc']['ice_servers']]}
        except FileNotFoundError:
            pass
        buffer = st.session_state['audio_buffer']
        ctx = webrtc_streamer(key='vinil-microfone', mode=WebRtcMode.SENDONLY,
            rtc_configuration=rtc_config,
            media_stream_constraints={'video': False, 'audio': {
                'echoCancellation': False, 'noiseSuppression': False, 'autoGainControl': False}},
            audio_frame_callback=buffer.receive, on_audio_ended=buffer.reset,
            async_processing=False)
        st.caption('Use START para iniciar e STOP para encerrar. Mantenha esta página aberta e a tela ativa.')

        @st.fragment(run_every=2)
        def live():
            if ctx.state.playing:
                now = time.monotonic()
                pcm = buffer.clip()
                if pcm is not None and now - st.session_state['last_attempt'] >= interval:
                    st.session_state['last_attempt'] = now
                    amplitude = np.frombuffer(pcm, dtype='<i2').astype(np.float64)
                    if np.sqrt(np.mean(amplitude ** 2)) > 60:
                        with st.spinner('Identificando o som do disco...'):
                            recognize(pcm_to_wav(pcm))
                    else:
                        st.session_state['notice'] = 'Som muito baixo. Aproxime o microfone das caixas.'
                st.caption('Microfone ativo. A primeira consulta precisa de cerca de 10 segundos de áudio.')
            else:
                st.caption('Microfone desligado. A imagem abaixo mostra a última música identificada.')
            show_results()

        # Defined before live() is invoked, also reused by manual mode.
    else:
        audio = st.audio_input('Grave de 10 a 15 segundos da música', sample_rate=16000)
        if st.button('Identificar música', type='primary', disabled=audio is None):
            with st.spinner('Identificando o som do disco...'):
                recognize(audio.getvalue())

    def show_results():
        st.info(st.session_state['notice'])
        try:
            flush_pending()
        except Exception:
            st.warning('O Google Sheets não recebeu os registros. Eles estão pendentes nesta sessão; mantenha a página aberta e confira as credenciais e os cabeçalhos.')
            if st.button('Tentar salvar novamente', key='retry_save'):
                st.session_state['save_retry_at'] = 0
                st.rerun()
        display_song()
        st.caption(f"Consultas ao reconhecimento nesta sessão: {st.session_state['attempts']}")

    if mode == 'Automático':
        live()
    else:
        show_results()
else:
    # Navigating away removes the WebRTC component and ends capture.
    st.title('Histórico da coleção')
    st.caption('Datas e horários de identificação no fuso de São Paulo.')
    if st.session_state['pending']:
        try:
            flush_pending()
        except Exception:
            st.warning('Há registros pendentes nesta sessão. Confira a conexão com o Sheets.')
    st.button('Atualizar histórico')
    try:
        df = history()
    except Exception:
        st.error('Não foi possível acessar o histórico. Confira os Secrets, o compartilhamento da planilha e a aba Historico.')
        st.stop()
    if df.empty:
        st.info('O próximo disco pode estrear seu histórico.')
        st.stop()
    df['quando'] = pd.to_datetime(df['identificada_em'], utc=True, errors='coerce').dt.tz_convert('America/Sao_Paulo')
    query = st.text_input('Buscar música, artista ou álbum')
    if query:
        mask = df[['musica', 'artista', 'album']].astype(str).apply(
            lambda col: col.str.contains(query, case=False, regex=False)).any(axis=1)
        df = df[mask]
    dates = df['quando'].dropna()
    if not dates.empty:
        selected = st.date_input('Período', value=(dates.min().date(), dates.max().date()))
        if len(selected) == 2:
            df = df[df['quando'].dt.date.between(selected[0], selected[1])]
    df = df.sort_values('quando', ascending=False)
    a, b, c = st.columns(3)
    a.metric('Identificações', len(df))
    b.metric('Músicas diferentes', df['chave'].nunique())
    c.metric('Artistas', df['artista'].nunique())
    view = df.copy()
    view['data'] = view['quando'].dt.strftime('%d/%m/%Y')
    view['horario'] = view['quando'].dt.strftime('%H:%M:%S')
    view = view[['capa_url', 'musica', 'artista', 'album', 'data', 'horario', 'link']]
    st.dataframe(view, hide_index=True, use_container_width=True, row_height=72,
        column_config={'capa_url': st.column_config.ImageColumn('Capa', width='small'),
                       'musica': 'Música', 'artista': 'Artista', 'album': 'Álbum',
                       'data': 'Data', 'horario': 'Horário',
                       'link': st.column_config.LinkColumn('Ouvir', display_text='Abrir')})
    st.download_button('Exportar CSV', view.to_csv(index=False).encode('utf-8-sig'),
                       'historico_vinil.csv', 'text/csv')
