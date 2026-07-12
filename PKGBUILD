# Maintainer: texsd <texsd@users.noreply.github.com>

pkgname=mechrevo-ec-git
pkgver=0.1.0.r0.gc8646e3
pkgrel=2
pkgdesc="Mechrevo notebook EC direct control — power mode, fan curve, keyboard backlight"
arch=('any')
url="https://github.com/minortex/mech-forza-control"
license=('MIT')
depends=('python>=3.10')
makedepends=('python-build' 'python-installer' 'python-hatchling' 'git')
source=("$pkgname::git+$url.git")
sha256sums=('SKIP')

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
  python -m installer --destdir="$pkgdir" dist/*.whl
}
