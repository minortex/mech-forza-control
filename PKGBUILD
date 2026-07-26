# Maintainer: texsd <texsd@users.noreply.github.com>

pkgname=mech-forza-control-git
pkgver=0.1.0.r0.gc8646e3
pkgrel=5
pkgdesc="Mechrevo notebook EC direct control CLI (MFC) — power mode, fan curve, keyboard backlight"
arch=('any')
url="https://github.com/minortex/mech-forza-control"
license=('MIT')
depends=('python>=3.11')
optdepends=('mech-forza-kmod-dkms-git: GX4HRXL kernel EC bridge (recommended on Linux)')
makedepends=('python-build' 'python-installer' 'python-hatchling' 'git')
source=("$pkgname::git+$url.git")
sha256sums=('SKIP')
backup=('etc/mech-forza-control/fan-table.toml')

pkgver() {
  cd "$pkgname"
  git describe --long --tags | sed 's/^v//;s/\([^-]*-g\)/r\1/;s/-/./g'
}

build() {
  cd "$srcdir/$pkgname"
  python -m build --wheel --no-isolation
}

package() {
  cd "$srcdir/$pkgname"
  python -m installer --destdir="$pkgdir" dist/mech_forza_control-*.whl
  install -Dm644 src/data/fan-table.toml "$pkgdir/etc/mech-forza-control/fan-table.toml"
  install -Dm644 systemd/mech-forza-fan.service "$pkgdir/usr/lib/systemd/system/mech-forza-fan.service"
}
