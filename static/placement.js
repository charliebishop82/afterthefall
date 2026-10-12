// Geometry only. Utility coverage, unlocks and payment remain server decisions.
function siteFits(x, y, width, height, bounds, occupied) {
  return Number.isInteger(x) && Number.isInteger(y) && x >= 0 && y >= 0 &&
    x + width <= bounds.width && y + height <= bounds.height &&
    !occupied.some(r => x < r.x + r.width && x + width > r.x &&
      y < r.y + r.height && y + height > r.y);
}
function nearbySite(width, height, bounds, occupied, hall) {
  let best = null, distance = Infinity;
  for (let y = 0; y <= bounds.height - height; y++) {
    for (let x = 0; x <= bounds.width - width; x++) {
      if (!siteFits(x, y, width, height, bounds, occupied)) continue;
      const d = (x + width / 2 - hall.x - hall.width / 2) ** 2 +
        (y + height / 2 - hall.y - hall.height / 2) ** 2;
      if (d < distance) { best = {x, y}; distance = d; }
    }
  }
  return best;
}
if (typeof module !== 'undefined') module.exports = {siteFits, nearbySite};
