import React, { useState, useEffect } from 'react';

function Orario() {
  const [ora, setOra] = useState(new Date());

  useEffect(() => {
    const intervallo = setInterval(() => {
      setOra(new Date());
    }, 1000);

    return () => {
      clearInterval(intervallo);
    };
  }, []);

  return (
    <div>
      <h1>Orario corrente: {ora.toLocaleTimeString()}</h1>
    </div>
  );
}

export default Orario;