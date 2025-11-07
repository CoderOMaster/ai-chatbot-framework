def test_ai_chatbot_common_database_exports():
    from ai_chatbot_common.database import (
        get_mongo_client,
        get_db,
        check_db_health,
        close_mongo_client,
    )

    # Just ensure they are importable callables
    assert callable(get_mongo_client)
    assert callable(get_db)
    assert callable(check_db_health)
    assert callable(close_mongo_client)