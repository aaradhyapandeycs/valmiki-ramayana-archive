#!/usr/bin/env bash
set -euo pipefail
out="${1:?supply the generated site directory}"
fonts="$out/fonts"
revision=29b4ec6df2522a8aee279414b78a07910b065874
base="https://raw.githubusercontent.com/google/fonts/$revision/ofl"
mkdir -p "$fonts"

fetch_font() {
  local family=$1 upstream=$2 destination=$3 expected=$4
  curl --fail --silent --show-error --location --retry 3 --max-time 90     "$base/$family/$upstream" -o "$fonts/$destination.ttf"
  test "$(git hash-object "$fonts/$destination.ttf")" = "$expected"
  curl --fail --silent --show-error --location --retry 3 --max-time 90     "$base/$family/OFL.txt" -o "$fonts/$destination-OFL.txt"
}

fetch_font sourcesans3 'SourceSans3%5Bwght%5D.ttf' source-sans-3   d259aa494fe7117141a2752a998a52c172bbd42b
fetch_font notoserif 'NotoSerif%5Bwdth%2Cwght%5D.ttf' noto-serif   7664d59c95d6c589f7b15017a218f7a42b93f86d
fetch_font notoserifdevanagari 'NotoSerifDevanagari%5Bwdth%2Cwght%5D.ttf' noto-serif-devanagari   3d90da279fe70b5017d9b51f58772f0c9ea4146e
