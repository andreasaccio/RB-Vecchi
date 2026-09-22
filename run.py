from rbvecchi.config import load_settings
from rbvecchi.web import create_app

settings = load_settings()
app = create_app(settings)

if __name__ == "__main__":
    app.run(host=settings.listen_host, port=settings.listen_port, threaded=True)
