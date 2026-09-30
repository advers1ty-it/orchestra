function dupe(arr) {
  return [...new Set(arr)];
}

console.log(dupe([1, 2, 2, 3, 1]));