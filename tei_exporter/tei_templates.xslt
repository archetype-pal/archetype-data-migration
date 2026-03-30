<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">

<!--__HEADER__-->

  <xsl:template match="@*|node()">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>

  <xsl:template match="span[@data-dpt='location'][@data-dpt-loctype='locus']">
    <xsl:element name="pb">
      <xsl:attribute name="n">
        <xsl:value-of select="text()" />
      </xsl:attribute>
    </xsl:element>
  </xsl:template>

  <xsl:template match="span[@data-dpt='lb']"><lb/></xsl:template>

  <xsl:template match="span[@data-dpt='ex']">
    <ex><xsl:apply-templates/></ex>
  </xsl:template>

  <xsl:template match="em">
    <ex><xsl:apply-templates/></ex>
  </xsl:template>

  <xsl:template match="span[@data-dpt='supplied']">
    <supplied><xsl:apply-templates/></supplied>
  </xsl:template>

  <xsl:template match="span[@data-dpt='clause']">
    <xsl:element name="cl">
      <xsl:attribute name="type">
        <xsl:value-of select="@data-dpt-type" />
      </xsl:attribute>
      <xsl:apply-templates/>
    </xsl:element>
  </xsl:template>

  <xsl:template match="span[@data-dpt='person'][@data-dpt-type='name']">
    <persName><xsl:apply-templates/></persName>
  </xsl:template>

  <xsl:template match="span[@data-dpt='person'][@data-dpt-type='title']">
    <persName><roleName><xsl:apply-templates/></roleName></persName>
  </xsl:template>

</xsl:stylesheet>
