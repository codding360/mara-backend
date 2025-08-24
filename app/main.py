from flask import Flask
from flask_cors import CORS
from flask_restx import Api

from app.core.config import get_config
from app.api.v1.endpoints.books import api as books_api

def create_app():
    app = Flask(__name__)
    
    # Load configuration
    config = get_config()
    app.config.from_object(config)

    # Initialize CORS
    CORS(app, resources={r"/api/*": {"origins": config.CORS_ORIGINS}})

    # Initialize API with Swagger documentation
    api = Api(
        app,
        version=config.VERSION,
        title=config.PROJECT_NAME,
        description=config.DESCRIPTION,
        doc='/api/docs'
    )

    # Register API namespaces
    api.add_namespace(books_api, path=f"{config.API_V1_STR}/books")

    return app

app = create_app()

if __name__ == '__main__':
    app.run()