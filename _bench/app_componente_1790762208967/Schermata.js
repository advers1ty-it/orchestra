import React, { useState } from 'react';
import { View, Text, TouchableOpacity } from 'react-native';

const Schermata = () => {
  const [count, setCount] = useState(0);

  return (
    <View>
      <Text>{count}</Text>
      <TouchableOpacity onPress={() => setCount(count + 1)}>
        <Text>Incrementa</Text>
      </TouchableOpacity>
    </View>
  );
};

export default Schermata;