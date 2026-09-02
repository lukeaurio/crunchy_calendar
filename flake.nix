{
  description = "Development shell for crunchyCalendar";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { nixpkgs, ... }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forEachSystem = function:
        nixpkgs.lib.genAttrs supportedSystems (system:
          function (import nixpkgs { inherit system; }));
    in
    {
      devShells = forEachSystem (pkgs:
        {
        default = pkgs.mkShell {
          packages = [ pkgs.python3 ];
          shellHook = ''
            export PYTHONNOUSERSITE=1
          '';
        };
      });
    };
}
