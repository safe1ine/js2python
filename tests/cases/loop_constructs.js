function sum(arr) {
  var total = 0;
  for (var i = 0; i < arr.length; i += 1) {
    total += arr[i];
  }
  while (total < 0) {
    total += 1;
  }
  return total;
}
