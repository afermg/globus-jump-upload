{
  description = "Tools for uploading JUMP-lite data to a Globus collection";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      # Globus only publishes a single -latest.tgz; the version below documents
      # which release the pinned hash corresponds to. Bump both when upstream
      # ships a new release (Nix's hash check enforces reproducibility).
      gcpVersion = "3.2.8";

      gcpRaw = pkgs.stdenv.mkDerivation {
        pname = "globusconnectpersonal-raw";
        version = gcpVersion;
        src = pkgs.fetchurl {
          url = "https://downloads.globus.org/globus-connect-personal/linux/stable/globusconnectpersonal-latest.tgz";
          hash = "sha256-lU4DkjqY8h9i9iJo8fN3G+mQycDE41lAQ/U+atCSTDs=";
        };
        dontConfigure = true;
        dontBuild = true;
        dontFixup = true;
        installPhase = ''
          mkdir -p $out
          cp -r . $out/
        '';
      };

      globusconnectpersonal = pkgs.buildFHSEnv {
        name = "globusconnectpersonal";
        targetPkgs = pkgs: with pkgs; [
          bashInteractive
          coreutils
          which
          gnused
          gawk
          gnugrep
          python3
          glibc
          zlib
          openssl
        ];
        runScript = pkgs.writeShellScript "gcp-launch" ''
          exec ${gcpRaw}/globusconnectpersonal "$@"
        '';
      };

      pythonEnv = pkgs.python3.withPackages (p: with p; [
        requests
        urllib3
      ]);

    in {
      packages.${system} = {
        default = globusconnectpersonal;
        inherit globusconnectpersonal;
        globus-cli = pkgs.globus-cli;
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          globusconnectpersonal
          pkgs.globus-cli
          pythonEnv
        ];
        shellHook = ''
          echo "globus-cli            $(globus version 2>/dev/null | head -1)"
          echo "globusconnectpersonal $(globusconnectpersonal -version 2>/dev/null | tail -1)"
          echo "python3               $(python3 --version)"
        '';
      };
    };
}
