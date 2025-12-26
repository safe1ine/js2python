function counter(start) {
  let total = start;
  const step = 2;
  if (step > 1) {
    let inside = total + step;
    total = inside;
  }
  return total;
}
