// Function to remove duplicates from an array while preserving order
const dupe = arr => {
  const seen = new Set();
  const result = [];
  for (const item of arr) {
    if (!seen.has(item)) {
      seen.add(item);
      result.push(item);
    }
  }
  return result;
};

// Test the function with [1,2,2,3,1]
console.log(dupe([1, 2, 2, 3, 1]));
