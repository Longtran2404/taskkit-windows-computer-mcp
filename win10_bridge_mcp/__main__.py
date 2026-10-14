if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TaskKit.vn Windows Computer Bridge MCP")
    parser.add_argument('--permissions', action='store_true', help='Open local owner enrollment/pause/revoke UI; no MCP access')
    args = parser.parse_args()
    if args.permissions:
        from .owner_permissions import main
    else:
        from .server import main
    main()
