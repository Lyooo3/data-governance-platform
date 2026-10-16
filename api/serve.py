import uvicorn
from . import config
from .main import app

if __name__ == "__main__":
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=config.PORT, log_level="info", access_log=False
        )
    )
    app.state.request_shutdown = lambda: setattr(server, "should_exit", True)
    server.run()
