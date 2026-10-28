from app.config import Settings
from app.dispatch import dispatch, with_team


def test_every_post_starts_with_the_team_handle():
    assert with_team("a1slv", "[coffee_bar] · evacuate") == "a1slv · [coffee_bar] · evacuate"
    assert with_team("a1slv", "a1slv · [coffee_bar] · evacuate") == "a1slv · [coffee_bar] · evacuate"


def test_dry_run_and_missing_webhook_never_post():
    dry = dispatch(
        Settings(team="a1slv", dispatch_mode="dry", discord_webhook_url="https://example.invalid"), "evacuate"
    )
    assert dry["via"] == "dry-run" and dry["content"] == "a1slv · evacuate"
    unset = dispatch(Settings(team="a1slv", dispatch_mode="live", discord_webhook_url=""), "evacuate")
    assert unset["via"] == "none" and not unset["sent"]
