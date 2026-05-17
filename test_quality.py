from generators.quality_gate import validate_post

bad_posts = [
    'Wait, the user example says: "last line = isolated CTA"',
    'Let me write a post about $LUNC',
    'First, I need to check the data',
    '$LUNC is down 5% on $2M volume',  # This should be valid
]

for post in bad_posts:
    valid, msg = validate_post(post)
    print(f'"{post[:50]}..." -> {"✅" if valid else "❌"} {msg}')
