from open_webui.utils.channels import extract_mentions, replace_mentions


def test_extract_mentions_returns_user_mentions():
    mentions = extract_mentions('Hey <@U:user-1|Alice> can you check this?')
    assert mentions == [{'id_type': 'U', 'id': 'user-1'}]


def test_extract_mentions_returns_all_mention():
    mentions = extract_mentions('<@A:all|All> please look at this incident')
    assert mentions == [{'id_type': 'A', 'id': 'all'}]


def test_extract_mentions_returns_mixed_user_and_all_mentions():
    mentions = extract_mentions('<@A:all|All> ping <@U:user-1|Alice> too')
    assert {(m['id_type'], m['id']) for m in mentions} == {('A', 'all'), ('U', 'user-1')}


def test_replace_mentions_renders_all_mention_label():
    assert replace_mentions('<@A:all|All> the batch failed') == 'All the batch failed'
