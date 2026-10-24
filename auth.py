"""Single-account access gate. Credentials are supplied only by Streamlit Secrets."""
import base64
import hashlib
import hmac
import secrets
import time

import streamlit as st

ITERATIONS = 600_000


def make_password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def validate_hash(encoded):
    algorithm, rounds, salt, digest = encoded.split('$')
    count = int(rounds)
    if algorithm != 'pbkdf2_sha256' or not 600_000 <= count <= 2_000_000:
        raise ValueError('Formato de hash inválido.')
    salt_bytes = base64.b64decode(salt, validate=True)
    digest_bytes = base64.b64decode(digest, validate=True)
    if len(salt_bytes) < 16 or len(digest_bytes) != 32:
        raise ValueError('Formato de hash inválido.')
    return count, salt_bytes, digest_bytes


def verify_password(password, encoded):
    count, salt, expected = validate_hash(encoded)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, count)
    return hmac.compare_digest(digest, expected)


def logout():
    audio = st.session_state.get('audio_buffer')
    if audio is not None:
        audio.reset()
    for key in list(st.session_state):
        del st.session_state[key]


def require_login():
    try:
        config = st.secrets['access']
        username = str(config['username']).strip()
        encoded = str(config['password_hash'])
        validate_hash(encoded)
        if not username:
            raise ValueError('Usuário vazio.')
    except (KeyError, ValueError, TypeError, FileNotFoundError):
        st.title('Lado A')
        st.info('Acesso privado. Configure [access] nos Secrets para habilitar o login. Consulte o README do projeto.')
        st.stop()

    signature = hashlib.sha256(f'{username}|{encoded}'.encode()).hexdigest()
    if hmac.compare_digest(str(st.session_state.get('_access_signature', '')), signature):
        return

    _, center, _ = st.columns([1, 1.25, 1])
    with center:
        st.markdown('<div class="hero-label">SUA COLEÇÃO. SEU ESPAÇO.</div>', unsafe_allow_html=True)
        st.title('Bem-vindo ao Lado A')
        st.caption('Entre para acompanhar seus discos e consultar o histórico.')
        with st.form('private_login', clear_on_submit=True):
            supplied_user = st.text_input('Usuário', max_chars=100)
            supplied_password = st.text_input('Senha', type='password', max_chars=1024)
            submit = st.form_submit_button('Entrar', type='primary', use_container_width=True)
        until = st.session_state.get('_login_blocked_until', 0)
        if time.monotonic() < until:
            st.warning('Muitas tentativas nesta sessão. Aguarde 30 segundos e tente novamente.')
        elif submit:
            # Verify even if the username differs, to avoid a fast user-name probe.
            password_ok = verify_password(supplied_password, encoded)
            user_ok = hmac.compare_digest(supplied_user.strip().encode(), username.encode())
            if password_ok and user_ok:
                st.session_state['_access_signature'] = signature
                st.session_state['_login_failures'] = 0
                st.rerun()
            else:
                failures = st.session_state.get('_login_failures', 0) + 1
                st.session_state['_login_failures'] = failures
                if failures >= 5:
                    st.session_state['_login_blocked_until'] = time.monotonic() + 30
                    st.session_state['_login_failures'] = 0
                st.error('Usuário ou senha incorretos.')
    st.stop()
