import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config(object):
    DEBUG = False
    TESTING = False
    # SECRET_KEY = os.environ.get('SECRET_KEY', '51f52814-0071-11e6-a2477-000ec6c2372c')
    # SQLALCHEMY_DATABASE_URI = os.environ.get(
    #     'DATABASE_URL', 'sqlite:///' + os.path.join(basedir, 'db.sqlite'))
    # SQLALCHEMY_TRACK_MODIFICATION = False
    REQUEST_STATS_WINDOW = 15


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    pass


class TestingConfig(Config):
    TESTING = True
    # SQLALCHEMY_DATABASE_URI = 'sqlite://'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig
}